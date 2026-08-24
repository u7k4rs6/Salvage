#!/usr/bin/env python3
"""One real end-to-end run against Razorpay test mode.

docs/01_PRD.md section 11 requires it: "a real test-mode Order, a real Payment Link created by the
agent, paid with a Razorpay test instrument, webhook received and verified, ledger entries shown".

This script is local only. It never runs in CI (docs/02_TECHNICAL_ARCHITECTURE.md section 15) and
it refuses to run without test-mode credentials. It creates real objects in a Razorpay test
account and no real money moves at any point.

What it does:
  1. Creates a real Order for a small amount.
  2. Creates a real Payment Link through the same client the agent uses, with reference_id set to
     the recovery case id, notify flags false, and expire_by at the case TTL.
  3. Prints the link and waits for you to pay it with a test instrument.
  4. Polls the link until it is paid, or, if a tunnel is pointed at the webhook endpoint, waits
     for the verified webhook to arrive.
  5. Saves the verified webhook payloads as CI fixtures.
  6. Prints every ledger sequence number the run produced and verifies the chain.

Which test instrument to use:
  A test card, by default. Razorpay's error parameters page states that UPI Collect is deprecated
  from 28 February 2026 under NPCI guidelines, with exemptions that do not include a plain test
  merchant, so a test UPI id entered by hand is not a reliable instrument for this run.
  https://razorpay.com/docs/errors/payment-error-parameters
  Test card details: https://razorpay.com/docs/payments/payments/test-card-details/
  Pass --instrument upi to try a test UPI id anyway; the flag exists so the question can be
  settled by experiment rather than by assumption, and the result belongs in docs/BUILD_LOG.md.

Usage:
  uv run python scripts/e2e_real_link.py --amount 100
  uv run python scripts/e2e_real_link.py --amount 100 --instrument upi
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from salvage import repo
from salvage.config import ConfigError, get_settings
from salvage.db import open_migrated
from salvage.decide.policy import ORDER_TTL_SECONDS
from salvage.execute import channels
from salvage.execute.razorpay_client import DuplicateReference, RazorpayClient, RazorpayError
from salvage.ledger import Ledger, verify

POLL_SECONDS = 5
DEFAULT_TIMEOUT_SECONDS = 600


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--amount", type=int, default=100, help="paise, default 100 (one rupee)")
    parser.add_argument(
        "--instrument",
        choices=["card", "upi"],
        default="card",
        help="which test instrument you intend to pay with; card by default, see the docstring",
    )
    parser.add_argument("--db", default=None)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--fixtures-out",
        default="tests/fixtures/webhooks",
        help="where verified webhook payloads are saved for CI replay",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    try:
        settings.require_razorpay_credentials()
    except ConfigError as exc:
        print(f"cannot run: {exc}", file=sys.stderr)
        print("Fill RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in .env first.", file=sys.stderr)
        return 2

    conn = open_migrated(args.db)
    ledger = Ledger(conn)
    client = RazorpayClient(settings=settings)
    first_seq = (ledger.head().seq + 1) if ledger.head() else 1

    try:
        return _run(conn, ledger, client, args, first_seq)
    finally:
        client.close()
        conn.close()


def _run(conn, ledger: Ledger, client: RazorpayClient, args, first_seq: int) -> int:
    now = int(time.time())
    case_id = f"case_e2e_{now}"

    print("1. Creating a real test-mode Order")
    order_response = client.create_order(
        amount=args.amount, receipt=case_id, notes={"salvage": "e2e"}
    )
    order_id = order_response.body["id"]
    print(f"   order_id={order_id} request_id={order_response.request_id}")
    ledger.append(
        "e2e.order.created",
        "order",
        order_id,
        {"amount": args.amount, "request_id": order_response.request_id},
        ts=now,
    )

    # The customer and order rows the agent would have. Contact details are not stored; only the
    # salted ref_hash, as docs/03_SECURITY_AND_ACCESS.md section 5 requires.
    customer_id = f"cust_e2e_{now}"
    if repo.get_customer(conn, customer_id) is None:
        repo.insert_customer(
            conn,
            {
                "id": customer_id,
                "ref_hash": repo.ref_hash(customer_id),
                "consent": 1,
                "locale": "en",
                "typical_amount": args.amount,
                "created_at": now,
            },
        )
    repo.upsert_order(
        conn,
        {
            "id": order_id,
            "customer_id": customer_id,
            "amount": args.amount,
            "currency": "INR",
            "status": "attempted",
            "source": "razorpay",
            "created_at": now,
        },
    )

    print("2. Creating a real Payment Link through the agent's own client")
    expire_by = now + ORDER_TTL_SECONDS
    try:
        link_response = client.create_payment_link(
            amount=args.amount,
            reference_id=case_id,
            expire_by=expire_by,
            description=f"Recovery link for order {order_id}",
        )
        link = link_response.body
        request_id = link_response.request_id
    except DuplicateReference:
        # The idempotency path. A create whose response was lost is recovered by reference rather
        # than by creating a second link for the same order.
        print("   duplicate reference_id, fetching the existing link instead")
        existing = client.fetch_payment_link_by_reference(case_id)
        if existing is None:
            print("   duplicate reported but no link found by reference", file=sys.stderr)
            return 1
        link, request_id = existing.body, existing.request_id

    link_id = link["id"]
    print(f"   link_id={link_id} request_id={request_id}")
    print(f"   notify flags: {link.get('notify')} (both must be false)")
    ledger.append(
        "e2e.link.created",
        "case",
        case_id,
        {
            "link_id": link_id,
            "order_id": order_id,
            "amount": args.amount,
            "reference_id": case_id,
            "expire_by": expire_by,
            "request_id": request_id,
        },
        ts=now,
    )

    message = channels.render(
        template_id="recovery_link_v1",
        locale="en",
        order_ref=order_id[-10:],
        link_url=str(link.get("short_url") or ""),
        expiry_text="72 hours",
    )
    print(f"3. Message the simulated channel would send (validator: {message.validation}):")
    print(f"   {message.body}")
    if not message.validation.ok:
        print("   validator refused the message, stopping", file=sys.stderr)
        return 1

    print()
    print(f"4. Pay this link with a Razorpay test {args.instrument}:")
    print(f"   {link.get('short_url')}")
    if args.instrument == "card":
        print(
            "   Test card details: https://razorpay.com/docs/payments/payments/test-card-details/"
        )
    else:
        print("   You chose UPI. If a test UPI id is refused, that answers the open question in")
        print("   docs/01_PRD.md section 16; record the result in docs/BUILD_LOG.md.")
    print()

    print("5. Waiting for the link to be paid")
    paid = _wait_for_payment(client, link_id, args.timeout)
    if paid is None:
        print("   timed out waiting for payment", file=sys.stderr)
        return 1
    payment_id = _payment_id_from(paid)
    print(f"   link status={paid.get('status')} payment_id={payment_id}")
    ledger.append(
        "e2e.link.paid",
        "case",
        case_id,
        {"link_id": link_id, "payment_id": payment_id, "amount_paid": paid.get("amount_paid")},
        ts=int(time.time()),
    )

    print("6. Webhook events received and verified for this run")
    events = _events_for(conn, order_id, link_id)
    for event in events:
        print(
            f"   {event['event_id']} {event['event_type']} verified={event['verified']} "
            f"acted={event['acted']}"
        )
    if events:
        written = _save_fixtures(events, Path(args.fixtures_out))
        print(f"   saved {written} verified payload(s) to {args.fixtures_out} for CI replay")
    else:
        print("   none. Point a tunnel at POST /api/webhooks/razorpay and run again to capture")
        print("   them, or replay a saved fixture with: salvage webhooks replay <dir>")

    print("7. Ledger entries produced by this run")
    for entry in ledger.iter_entries(since_seq=first_seq - 1):
        print(f"   seq={entry.seq} {entry.kind} ref={entry.ref_type}:{entry.ref_id}")
    result = verify(conn)
    print(f"   {result}")
    return 0 if result.ok else 1


def _wait_for_payment(client: RazorpayClient, link_id: str, timeout: int) -> dict | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            body = client.fetch_payment_link(link_id).body
        except RazorpayError as exc:
            print(f"   fetch failed, retrying: {exc}", file=sys.stderr)
            time.sleep(POLL_SECONDS)
            continue
        if body.get("status") == "paid":
            return body
        time.sleep(POLL_SECONDS)
    return None


def _payment_id_from(link: dict) -> str | None:
    payments = link.get("payments") or []
    if payments and isinstance(payments, list):
        return payments[0].get("payment_id") or payments[0].get("id")
    return None


def _events_for(conn, order_id: str, link_id: str) -> list[dict]:
    """Verified webhook events mentioning this order or link.

    A substring match on the stored raw body rather than a parsed lookup, because the events span
    several entity types and the point here is to show what arrived, not to normalise it again.
    """
    rows = repo.verified_webhook_events(conn)
    return [row for row in rows if order_id in row["raw_json"] or link_id in row["raw_json"]]


def _save_fixtures(events: list[dict], out_dir: Path) -> int:
    """Save verified payloads for CI replay.

    These are real webhook bodies from a test account. They can carry a contact and an email, so
    review them before committing, exactly as docs/03_SECURITY_AND_ACCESS.md section 10 requires
    for fixtures.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for event in events:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in event["event_id"])
        (out_dir / f"{int(event['received_at']):011d}_{safe}.json").write_text(
            json.dumps(
                {
                    "event_id": event["event_id"],
                    "received_at": event["received_at"],
                    "event_type": event["event_type"],
                    "body": event["raw_json"],
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
    return len(events)


if __name__ == "__main__":
    raise SystemExit(main())
