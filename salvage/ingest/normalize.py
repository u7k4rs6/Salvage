"""Normalise Razorpay payment entities into database rows.

Architecture section 4: "Simulated events are produced by the simulator in the same shape
(payment entity fields, including error_code, error_source, error_step, error_reason,
error_description, method, vpa, card.network, card.issuer, card.iin and bank) and go through the
same normaliser, so the detector cannot tell the two sources apart."

That is the whole point of this module: one function, two callers. If the simulator ever needed a
second code path here, the measurement would stop being honest.

Field shapes are from razorpay.com/docs/api/payments/entity/ and
razorpay.com/docs/webhooks/payloads/payments/ (both fetched 24 August 2026):

  status         created, authorized, captured, refunded, failed
  method         upi, card, netbanking, wallet, emi, ...
  vpa            "gauravkumar@exampleupi", UPI only
  bank           4-character bank code, "UTIB", netbanking and UPI
  wallet         wallet code, wallet only
  card           object with last4, network, type, issuer, and the iin
  error_*        error_code, error_description, error_source, error_step, error_reason

Everything Razorpay might add later survives: the entity is stored verbatim in raw_json, and the
error enums pass unknown values through (salvage/taxonomy.py).
"""

from __future__ import annotations

import json
from typing import Any

from salvage import taxonomy

# Payment statuses Salvage records. Anything else is stored with its Razorpay status verbatim, so
# a new status does not silently become "failed".
FAILED = "failed"
AUTHORIZED = "authorized"
CAPTURED = "captured"


class NormaliseError(ValueError):
    """The payload is not a payment entity we can use."""


def _card_field(entity: dict[str, Any], name: str) -> Any:
    card = entity.get("card")
    if isinstance(card, dict):
        return card.get(name)
    return None


def _upi_handle(entity: dict[str, Any]) -> str | None:
    """The handle is the part of the VPA after the '@'.

    Razorpay does not expose the handle as its own field, so it is derived here. That derivation
    is the one assumption in this module and it is isolated to this function: if Razorpay adds a
    handle field, only this function changes.
    """
    vpa = entity.get("vpa")
    if not isinstance(vpa, str) or "@" not in vpa:
        return None
    handle = vpa.rsplit("@", 1)[1].strip().lower()
    return handle or None


def _card_bin(entity: dict[str, Any]) -> str | None:
    """Six-digit BIN. Razorpay's payment entity carries the card's iin; where a payload has only
    a token_iin (a network token, not the real card), that is used instead and is still a stable
    per-instrument key for segmentation."""
    for field in ("iin", "token_iin"):
        value = _card_field(entity, field)
        if isinstance(value, str) and value.strip():
            return value.strip()[:6]
    return None


def normalize_payment_entity(
    entity: dict[str, Any],
    *,
    customer_id: str,
    truth_cause: str | None = None,
) -> dict[str, Any]:
    """One Razorpay payment entity to one payment_attempts row.

    customer_id is supplied by the caller: Razorpay's payment entity has no Salvage customer id,
    so ingest resolves it from the order and the simulator knows it directly.

    truth_cause is simulator-only ground truth. Webhook ingest always leaves it None.
    """
    payment_id = entity.get("id")
    order_id = entity.get("order_id")
    if not payment_id:
        raise NormaliseError("payment entity has no id")
    if not order_id:
        raise NormaliseError(f"payment {payment_id} has no order_id")

    method = entity.get("method")
    if not method:
        raise NormaliseError(f"payment {payment_id} has no method")

    status = entity.get("status") or FAILED

    return {
        "id": str(payment_id),
        "order_id": str(order_id),
        "customer_id": customer_id,
        "method": str(method),
        "upi_handle": _upi_handle(entity),
        "card_bin": _card_bin(entity),
        "card_network": _card_field(entity, "network"),
        "card_issuer": _card_field(entity, "issuer"),
        # Razorpay puts the 4-character bank code in `bank` for netbanking and for UPI. For
        # wallets the instrument is in `wallet`, and it is stored in the same column so one
        # segment key covers "which instrument inside this method".
        "nb_bank": entity.get("bank") or entity.get("wallet"),
        "status": str(status),
        "error_code": entity.get("error_code"),
        "error_source": taxonomy.coerce_source(entity.get("error_source")),
        "error_step": taxonomy.coerce_step(entity.get("error_step")),
        "error_reason": taxonomy.coerce_reason(entity.get("error_reason")),
        "error_description": entity.get("error_description"),
        "created_at": int(entity.get("created_at") or 0),
        "raw_json": json.dumps(entity, sort_keys=True, separators=(",", ":")),
        "truth_cause": truth_cause,
    }


def normalize_order_from_payment(
    entity: dict[str, Any], *, customer_id: str, source: str
) -> dict[str, Any]:
    """The order row a payment entity implies.

    Razorpay's payment entity carries the order id and the amount but not the order's own
    created_at, so the payment's created_at is used. upsert_order keeps whichever created_at
    arrived first for an existing row, so a later payment never rewrites the order's age.
    """
    status = "paid" if entity.get("status") == CAPTURED else "attempted"
    return {
        "id": str(entity["order_id"]),
        "customer_id": customer_id,
        "amount": int(entity.get("amount") or 0),
        "currency": entity.get("currency") or "INR",
        "status": status,
        "source": source,
        "created_at": int(entity.get("created_at") or 0),
        "paid_at": int(entity["created_at"]) if entity.get("status") == CAPTURED else None,
    }
