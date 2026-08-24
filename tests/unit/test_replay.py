"""Record and replay: Architecture section 4, security doc section 4."""

from __future__ import annotations

import json

import pytest

from salvage import repo
from salvage.config import Settings
from salvage.ingest.replay import ReplayRefused, record_verified_events, replay_directory
from salvage.ingest.webhooks import ingest_event

SECRET = "webhook_secret_for_tests"


def _settings(env: str = "dev") -> Settings:
    return Settings(
        razorpay_key_id="",
        razorpay_key_secret="",
        razorpay_webhook_secret=SECRET,
        salvage_env=env,
        salvage_ref_hash_salt="test-salt",
        _env_file=None,
    )


def _event(payment_id: str) -> dict:
    return {
        "entity": "event",
        "event": "payment.failed",
        "contains": ["payment"],
        "created_at": 1785522600,
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "entity": "payment",
                    "amount": 120000,
                    "currency": "INR",
                    "status": "failed",
                    "order_id": f"order_{payment_id}",
                    "method": "card",
                    "card": {"iin": "411111", "network": "Visa", "issuer": "HDFC", "last4": "1111"},
                    "contact": "+919876543210",
                    "error_code": "GATEWAY_ERROR",
                    "error_description": "Your payment was declined by your bank.",
                    "error_source": "issuer_bank",
                    "error_step": "payment_authorization",
                    "error_reason": "card_declined",
                    "created_at": 1785522600,
                }
            }
        },
    }


def _receive(conn, payment_id: str, event_id: str, *, verified: bool = True) -> None:
    event = _event(payment_id)
    ingest_event(
        conn,
        event=event,
        event_id=event_id,
        raw_body=json.dumps(event).encode(),
        received_at=1785522700,
        verified=verified,
        settings=_settings(),
    )


def test_record_writes_one_file_per_verified_event(conn, tmp_path):
    _receive(conn, "pay_r1", "evt_r1")
    _receive(conn, "pay_r2", "evt_r2")
    _receive(conn, "pay_r3", "evt_r3", verified=False)

    out = tmp_path / "webhooks"
    written = record_verified_events(conn, out)
    assert written == 2
    files = sorted(out.glob("*.json"))
    assert len(files) == 2
    record = json.loads(files[0].read_text())
    assert set(record) == {"event_id", "received_at", "event_type", "body"}
    assert json.loads(record["body"])["event"] == "payment.failed"


def test_replay_reingests_through_the_same_normaliser(conn, tmp_path):
    _receive(conn, "pay_x1", "evt_x1")
    out = tmp_path / "webhooks"
    record_verified_events(conn, out)

    fresh = _fresh_db(tmp_path)
    try:
        summary = replay_directory(fresh, out, settings=_settings("dev"))
        assert summary.replayed == 1
        assert summary.duplicates == 0
        attempt = repo.get_attempt(fresh, "pay_x1")
        assert attempt["card_bin"] == "411111"
        assert attempt["error_reason"] == "card_declined"
        # The replay path did not verify a signature, and the record says so.
        assert repo.get_webhook_event(fresh, "evt_x1")["verified"] == 0
    finally:
        fresh.close()


def test_replaying_twice_is_idempotent(conn, tmp_path):
    _receive(conn, "pay_y1", "evt_y1")
    out = tmp_path / "webhooks"
    record_verified_events(conn, out)

    fresh = _fresh_db(tmp_path)
    try:
        first = replay_directory(fresh, out, settings=_settings("dev"))
        second = replay_directory(fresh, out, settings=_settings("dev"))
        assert first.replayed == 1 and first.duplicates == 0
        assert second.replayed == 0 and second.duplicates == 1
        assert repo.count_webhook_events(fresh) == 1
    finally:
        fresh.close()


def test_replay_is_refused_outside_dev(conn, tmp_path):
    out = tmp_path / "webhooks"
    out.mkdir()
    with pytest.raises(ReplayRefused, match="SALVAGE_ENV=dev"):
        replay_directory(conn, out, settings=_settings("demo"))


def test_replay_skips_unusable_files(conn, tmp_path):
    out = tmp_path / "webhooks"
    out.mkdir()
    (out / "a.json").write_text(json.dumps({"event_id": "e", "body": "not json"}))
    (out / "b.json").write_text(json.dumps({"received_at": 1}))
    summary = replay_directory(conn, out, settings=_settings("dev"))
    assert summary.replayed == 0
    assert summary.skipped == 2


def _fresh_db(tmp_path):
    from salvage.db import open_migrated

    return open_migrated(tmp_path / "fresh.db")
