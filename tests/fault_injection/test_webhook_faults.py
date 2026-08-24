"""Webhook faults: duplicate, out of order, bad signature, stale, and clock skew.

Architecture section 15 and docs/03_SECURITY_AND_ACCESS.md section 4.
"""

from __future__ import annotations

import json

import pytest

from salvage import repo
from salvage.config import Settings, reset_settings_cache
from salvage.db import open_migrated
from salvage.ingest.webhooks import compute_signature, ingest_event, verify_signature
from salvage.ledger import Ledger, verify

SECRET = "webhook_secret_for_tests"


def _settings(env: str = "dev") -> Settings:
    return Settings(
        razorpay_key_id="",
        razorpay_key_secret="",
        razorpay_webhook_secret=SECRET,
        salvage_env=env,
        salvage_ref_hash_salt="t",
        _env_file=None,
    )


def _event(event_type: str = "payment.failed", status: str = "failed", **overrides) -> dict:
    payment = {
        "id": "pay_inj0000000001",
        "entity": "payment",
        "amount": 250000,
        "currency": "INR",
        "status": status,
        "order_id": "order_inj000000001",
        "method": "upi",
        "vpa": "someone@okhdfcbank",
        "bank": "HDFC",
        "contact": "+919876543210",
        "email": "someone@example.com",
        "error_code": "GATEWAY_ERROR",
        "error_description": "Payment failed due to a technical error at bank.",
        "error_source": "bank",
        "error_step": "payment_authorization",
        "error_reason": "bank_technical_error",
        "created_at": 1785522600,
    }
    payment.update(overrides.pop("payment", {}))
    return {
        "entity": "event",
        "event": event_type,
        "contains": ["payment"],
        "payload": {"payment": {"entity": payment}},
        "created_at": payment["created_at"],
    }


@pytest.fixture
def conn(tmp_path):
    reset_settings_cache()
    connection = open_migrated(tmp_path / "wh.db")
    yield connection
    connection.close()
    reset_settings_cache()


def _ingest(conn, event, event_id, *, verified=True, received_at=1785522700, env="dev"):
    return ingest_event(
        conn,
        event=event,
        event_id=event_id,
        raw_body=json.dumps(event).encode(),
        received_at=received_at,
        verified=verified,
        settings=_settings(env),
    )


def test_a_forged_signature_never_verifies(injection_log):
    body = json.dumps(_event()).encode()
    forged = [
        "",
        "0" * 64,
        compute_signature(body, "the_wrong_secret"),
        compute_signature(body + b" ", SECRET),
        compute_signature(b"", SECRET),
    ]
    for signature in forged:
        assert not verify_signature(body, signature, SECRET)
    injection_log.record(
        category="webhook",
        attack="forged or wrong-secret signature",
        refused=True,
        ledgered=False,
        detail=f"{len(forged)} forgeries, none verified",
    )


def test_a_replayed_event_id_changes_nothing(conn, injection_log):
    first = _ingest(conn, _event(), "evt_dup")
    assert first.acted
    attempt_before = repo.get_attempt(conn, "pay_inj0000000001")

    # The attacker replays the same event id with a captured body claiming the payment succeeded.
    second = _ingest(conn, _event(status="captured"), "evt_dup")
    assert second.duplicate
    assert not second.acted
    assert repo.get_attempt(conn, "pay_inj0000000001") == attempt_before
    assert repo.count_webhook_events(conn) == 1
    assert verify(conn).ok
    injection_log.record(
        category="webhook",
        attack="replayed event id claiming a different outcome",
        refused=True,
        ledgered=True,
        detail="dedupe on the unique index, nothing applied",
    )


def test_an_out_of_order_failure_cannot_unpay_a_captured_payment(conn, injection_log):
    _ingest(conn, _event("payment.captured", status="captured"), "evt_cap")
    _ingest(conn, _event("payment.failed", status="failed"), "evt_fail")
    assert repo.get_attempt(conn, "pay_inj0000000001")["status"] == "captured"
    assert repo.get_order(conn, "order_inj000000001")["status"] == "paid"
    injection_log.record(
        category="webhook",
        attack="out-of-order failure after a capture",
        refused=True,
        ledgered=True,
        detail="captured state is sticky, order stays paid",
    )


def test_a_stale_event_in_demo_mode_is_flagged_and_not_acted_on(conn, injection_log):
    event = _event()
    result = _ingest(conn, event, "evt_stale", received_at=event["created_at"] + 7200, env="demo")
    assert result.stale
    assert not result.acted
    assert repo.count_attempts(conn) == 0
    assert repo.get_webhook_event(conn, "evt_stale")["stale"] == 1
    injection_log.record(
        category="webhook",
        attack="stale event replayed hours later in demo mode",
        refused=True,
        ledgered=True,
        detail="stored and flagged, no state change",
    )


def test_clock_skew_backwards_does_not_make_an_event_stale(conn, injection_log):
    """A receiver whose clock is behind must not silently drop good events."""
    event = _event()
    result = _ingest(conn, event, "evt_skew", received_at=event["created_at"] - 300, env="demo")
    assert not result.stale
    assert result.acted
    injection_log.record(
        category="webhook",
        attack="receiver clock five minutes behind",
        refused=False,
        ledgered=True,
        detail="within the freshness window in either direction, acted on",
        expect_refusal=False,
    )


def test_clock_skew_beyond_the_window_is_treated_as_stale(conn, injection_log):
    event = _event()
    result = _ingest(conn, event, "evt_skew2", received_at=event["created_at"] - 7200, env="demo")
    assert result.stale
    assert not result.acted
    injection_log.record(
        category="webhook",
        attack="receiver clock two hours out",
        refused=True,
        ledgered=True,
        detail="outside the freshness window, flagged and not acted on",
    )


def test_an_unhandled_event_type_changes_no_state(conn, injection_log):
    result = _ingest(conn, _event("payment.dispute.created"), "evt_unknown")
    assert not result.acted
    assert repo.count_attempts(conn) == 0
    injection_log.record(
        category="webhook",
        attack="event type outside the handled set",
        refused=True,
        ledgered=True,
    )


def test_every_verified_event_leaves_a_ledger_entry_without_the_contact(conn, injection_log):
    _ingest(conn, _event(), "evt_led")
    payloads = " ".join(
        row["payload_json"] for row in conn.execute("SELECT payload_json FROM ledger")
    )
    assert "webhook.received" in [entry.kind for entry in Ledger(conn).entries()]
    assert "+919876543210" not in payloads
    assert "someone@example.com" not in payloads
    assert verify(conn).ok
    injection_log.record(
        category="webhook",
        attack="contact details in a webhook body reaching the ledger",
        refused=True,
        ledgered=True,
        detail="ledger carries ids and the outcome, never the body",
    )
