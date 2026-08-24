"""Razorpay webhook receiver.

docs/03_SECURITY_AND_ACCESS.md section 4 and Architecture section 4.

  Endpoint POST /api/webhooks/razorpay, unauthenticated by design, because Razorpay cannot
  present a bearer token. Verification is the authentication.

  Verification: HMAC-SHA256 of the raw request body using the webhook secret, hex encoded,
  compared with X-Razorpay-Signature using hmac.compare_digest. The body is read as bytes before
  any JSON parsing so the signature is computed over exactly what Razorpay signed.

  Idempotency: X-Razorpay-Event-Id is stored with a unique index; duplicates return 200 and do
  nothing.

  Freshness: in demo mode the payload's created_at must be within 15 minutes of receipt; older
  events are stored, flagged and not acted on.

  Replay: the unsigned replay path exists only when SALVAGE_ENV=dev and is not registered on the
  router otherwise.

An event that fails verification is rejected and not stored. Storing it would let anyone with the
URL fill the database, and the security doc's own framing is that verification is the
authentication, so an unverified body is an unauthenticated write.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from salvage import repo
from salvage.config import ConfigError, Settings, get_settings
from salvage.db import open_migrated
from salvage.ingest.normalize import normalize_order_from_payment, normalize_payment_entity
from salvage.ledger import Ledger

SIGNATURE_HEADER = "X-Razorpay-Signature"
EVENT_ID_HEADER = "X-Razorpay-Event-Id"

# Architecture section 4 fixes the handled set.
HANDLED_EVENTS = frozenset(
    {
        "payment.failed",
        "payment.captured",
        "order.paid",
        "payment_link.paid",
        "payment_link.cancelled",
        "payment_link.expired",
    }
)


class SignatureError(ValueError):
    """The signature did not verify."""


def compute_signature(body: bytes, secret: str) -> str:
    """HMAC-SHA256 of the raw body, hex encoded. Exactly what Razorpay documents."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify_signature(body: bytes, signature: str | None, secret: str) -> bool:
    """Constant-time comparison. A missing signature is a failure, not an exception."""
    if not signature:
        return False
    return hmac.compare_digest(compute_signature(body, secret), signature)


def is_stale(event: dict[str, Any], received_at: int, settings: Settings) -> bool:
    """Freshness check. Only demo mode enforces it (security doc section 4).

    A payload with no created_at is treated as fresh: Razorpay always sends one, and refusing to
    act on an event because a field we do not control is missing would be worse than acting.
    """
    if settings.salvage_env != "demo":
        return False
    created_at = event.get("created_at")
    if not isinstance(created_at, int):
        return False
    return abs(received_at - created_at) > settings.webhook_freshness_seconds


@dataclass(frozen=True)
class IngestResult:
    event_id: str
    event_type: str
    accepted: bool
    duplicate: bool
    stale: bool
    acted: bool
    detail: str


def _resolve_customer_id(conn, entity: dict[str, Any], order_id: str | None) -> str:
    """Find or create the Salvage customer for a real Razorpay payment.

    Razorpay's payment entity has no Salvage customer id. If the order is already known, its
    customer is the answer. Otherwise a customer is created from the salted hash of whatever
    identifier the payload carries, falling back to the order id, so a real payment for an order
    Salvage did not create still lands somewhere sensible.

    Only the ref_hash is stored. The raw contact and email stay in webhook_events.raw_json, which
    is excluded from logs and exports (security doc section 5).
    """
    if order_id:
        order = repo.get_order(conn, order_id)
        if order:
            return str(order["customer_id"])

    raw_identifier = entity.get("contact") or entity.get("email") or order_id or entity.get("id")
    digest = repo.ref_hash(str(raw_identifier))
    customer_id = f"cust_wh_{digest[:16]}"
    if repo.get_customer(conn, customer_id) is None:
        repo.insert_customer(
            conn,
            {
                "id": customer_id,
                "ref_hash": digest,
                # No consent is recorded for a customer Salvage has never met. The policy engine
                # refuses to contact them, which is the correct default.
                "consent": 0,
                "locale": "en",
                "preferred_method": entity.get("method"),
                "typical_amount": int(entity.get("amount") or 0),
                "created_at": int(entity.get("created_at") or time.time()),
            },
        )
    return customer_id


def _apply_payment(conn, entity: dict[str, Any]) -> str:
    order_id = entity.get("order_id")
    customer_id = _resolve_customer_id(conn, entity, order_id)
    order_row = normalize_order_from_payment(entity, customer_id=customer_id, source="razorpay")
    repo.upsert_order(conn, order_row)
    attempt_row = normalize_payment_entity(entity, customer_id=customer_id)
    repo.upsert_attempt(conn, attempt_row)
    return f"payment {attempt_row['id']} status {attempt_row['status']}"


def _apply_order_paid(conn, entity: dict[str, Any]) -> str:
    order_id = entity.get("id")
    if not order_id:
        return "order.paid with no order id, ignored"
    if repo.get_order(conn, str(order_id)) is None:
        return f"order {order_id} unknown, ignored"
    paid_at = int(entity.get("created_at") or time.time())
    repo.mark_order_paid(conn, str(order_id), paid_at)
    return f"order {order_id} marked paid"


def _apply_payment_link(conn, entity: dict[str, Any], event_type: str) -> str:
    """Payment link outcomes.

    M1 creates no links, so there is never a case to update. The lookup is here rather than in M2
    so an out-of-order or replayed link event is a no-op today and correct tomorrow, and so the
    ledger records the event either way.
    """
    link_id = entity.get("id")
    if not link_id:
        return f"{event_type} with no link id, ignored"
    row = conn.execute(
        "SELECT id FROM recovery_cases WHERE link_id = ?", (str(link_id),)
    ).fetchone()
    if row is None:
        return f"{event_type} for link {link_id}, no matching recovery case"
    return f"{event_type} for link {link_id}, case {row['id']}"


def ingest_event(
    conn,
    *,
    event: dict[str, Any],
    event_id: str,
    raw_body: bytes,
    received_at: int,
    verified: bool,
    settings: Settings,
) -> IngestResult:
    """Store and apply one verified event. Idempotent on event_id.

    The dedupe is the unique index on webhook_events.event_id, not a prior SELECT, so two
    concurrent deliveries of the same event cannot both pass a check and both act.
    """
    event_type = str(event.get("event") or "")
    stale = is_stale(event, received_at, settings)

    inserted = repo.insert_webhook_event(
        conn,
        {
            "event_id": event_id,
            "received_at": received_at,
            "verified": int(verified),
            "raw_json": raw_body.decode("utf-8", errors="replace"),
            "event_type": event_type,
            "stale": int(stale),
            "acted": 0,
        },
    )
    if not inserted:
        return IngestResult(
            event_id=event_id,
            event_type=event_type,
            accepted=True,
            duplicate=True,
            stale=stale,
            acted=False,
            detail="duplicate event id, no action taken",
        )

    if event_type not in HANDLED_EVENTS:
        detail = f"event type {event_type!r} is not handled"
        acted = False
    elif stale:
        detail = "event is outside the freshness window, stored and flagged, not acted on"
        acted = False
    else:
        payload = event.get("payload") or {}
        if event_type in ("payment.failed", "payment.captured"):
            entity = (payload.get("payment") or {}).get("entity") or {}
            detail = _apply_payment(conn, entity)
        elif event_type == "order.paid":
            entity = (payload.get("order") or {}).get("entity") or {}
            detail = _apply_order_paid(conn, entity)
        else:
            entity = (payload.get("payment_link") or {}).get("entity") or {}
            detail = _apply_payment_link(conn, entity, event_type)
        acted = True
        repo.mark_webhook_acted(conn, event_id)

    # One ledger entry per verified event. The payload carries ids and the outcome, never the
    # body: raw_json can contain a contact or an email and the ledger must not (security doc
    # section 5).
    Ledger(conn).append(
        "webhook.received",
        "webhook_event",
        event_id,
        {
            "event_type": event_type,
            "verified": verified,
            "stale": stale,
            "acted": acted,
            "detail": detail,
        },
        ts=received_at,
    )

    return IngestResult(
        event_id=event_id,
        event_type=event_type,
        accepted=True,
        duplicate=False,
        stale=stale,
        acted=acted,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def get_conn() -> Iterator[Any]:
    """One connection per request. SQLite in WAL mode, single process, so this is cheap.

    Declared as a dependency so tests can point the endpoint at a temporary database without
    touching the environment or the settings cache.
    """
    conn = open_migrated()
    try:
        yield conn
    finally:
        conn.close()


ConnDep = Annotated[Any, Depends(get_conn)]


async def razorpay_webhook(
    request: Request,
    response: Response,
    conn: ConnDep,
    x_razorpay_signature: Annotated[str | None, Header()] = None,
    x_razorpay_event_id: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    settings = get_settings()
    try:
        secret = settings.require_webhook_secret()
    except ConfigError as exc:
        # The server cannot verify anything without the secret. 503 rather than 500, because this
        # is a deployment state, not a bug, and Razorpay will retry.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # Read the raw bytes before anything parses them, so the signature is computed over exactly
    # what Razorpay signed.
    body = await request.body()

    if not verify_signature(body, x_razorpay_signature, secret):
        raise HTTPException(status_code=400, detail="signature verification failed")

    if not x_razorpay_event_id:
        raise HTTPException(status_code=400, detail=f"missing {EVENT_ID_HEADER}")

    try:
        event = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="body is not JSON") from exc
    if not isinstance(event, dict):
        raise HTTPException(status_code=400, detail="body is not a JSON object")

    result = ingest_event(
        conn,
        event=event,
        event_id=x_razorpay_event_id,
        raw_body=body,
        received_at=int(time.time()),
        verified=True,
        settings=settings,
    )

    response.status_code = 200
    return {
        "event_id": result.event_id,
        "duplicate": result.duplicate,
        "stale": result.stale,
        "acted": result.acted,
    }


async def razorpay_replay_unsigned(
    request: Request,
    conn: ConnDep,
    x_razorpay_event_id: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    """Unsigned replay. Registered only when SALVAGE_ENV=dev; see build_router."""
    settings = get_settings()
    # Defence in depth: the route is not registered outside dev, and if it somehow is, it refuses.
    if not settings.is_dev:
        raise HTTPException(status_code=404, detail="not found")
    body = await request.body()
    if not x_razorpay_event_id:
        raise HTTPException(status_code=400, detail=f"missing {EVENT_ID_HEADER}")
    try:
        event = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="body is not JSON") from exc
    result = ingest_event(
        conn,
        event=event,
        event_id=x_razorpay_event_id,
        raw_body=body,
        received_at=int(time.time()),
        verified=False,
        settings=settings,
    )
    return {"event_id": result.event_id, "duplicate": result.duplicate, "acted": result.acted}


def build_router(*, include_dev_replay: bool) -> APIRouter:
    """A fresh router per application.

    Not a module-level singleton, and this is the reason: a singleton that
    register_dev_replay_route() mutated kept the unsigned replay route for the rest of the
    process, so a demo-mode app created after a dev-mode one in the same interpreter still
    carried it. A test caught that; see docs/BUILD_LOG.md. Building the router per app means
    "compiled out of the router otherwise" is literally true.
    """
    router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])
    router.post("/razorpay")(razorpay_webhook)
    if include_dev_replay:
        router.post("/razorpay/replay")(razorpay_replay_unsigned)
    return router
