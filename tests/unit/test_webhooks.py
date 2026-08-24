"""Webhook security and idempotency: docs/03_SECURITY_AND_ACCESS.md section 4.

The four cases the M1 brief names: valid signature accepted, bad signature rejected, duplicate
event id is a no-op, out-of-order events are safe.
"""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from salvage import repo
from salvage.api.app import create_app
from salvage.config import Settings, reset_settings_cache
from salvage.ingest.webhooks import (
    compute_signature,
    ingest_event,
    is_stale,
    verify_signature,
)
from salvage.ledger import verify

SECRET = "webhook_secret_for_tests"


def _settings(**overrides) -> Settings:
    base = {
        "razorpay_key_id": "",
        "razorpay_key_secret": "",
        "razorpay_webhook_secret": SECRET,
        "salvage_env": "dev",
        "salvage_ref_hash_salt": "test-salt",
        "_env_file": None,
    }
    base.update(overrides)
    return Settings(**base)


def _event(event_type: str = "payment.failed", **overrides) -> dict:
    """A Razorpay event envelope, shaped as razorpay.com/docs/webhooks/payloads/payments/."""
    payment = {
        "id": "pay_test0000000001",
        "entity": "payment",
        "amount": 250000,
        "currency": "INR",
        "status": "failed",
        "order_id": "order_test000000001",
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
    event = {
        "entity": "event",
        "account_id": "acc_test",
        "event": event_type,
        "contains": ["payment"],
        "payload": {"payment": {"entity": payment}},
        "created_at": payment["created_at"],
    }
    event.update(overrides)
    return event


def _post(client: TestClient, event: dict, *, event_id: str, signature: str | None = None):
    body = json.dumps(event).encode()
    if signature is None:
        signature = compute_signature(body, SECRET)
    headers = {"X-Razorpay-Event-Id": event_id}
    if signature != "":
        headers["X-Razorpay-Signature"] = signature
    return client.post("/api/webhooks/razorpay", content=body, headers=headers)


@pytest.fixture
def web_db(tmp_path, monkeypatch):
    """A real database file the endpoint and the test both open.

    Not a shared connection object handed to the endpoint: the endpoint opens its own connection
    on whichever thread pool thread runs the request, which is the whole point of the per-thread
    connection change, and a test that bypassed that would stop testing it.
    """
    from salvage.db import close_thread_connections, open_migrated

    path = tmp_path / "webhooks.db"
    monkeypatch.setenv("SALVAGE_DB_PATH", str(path))
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("SALVAGE_ENV", "dev")
    monkeypatch.setenv("SALVAGE_REF_HASH_SALT", "test-salt")
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    reset_settings_cache()
    close_thread_connections()
    connection = open_migrated(path)
    try:
        yield connection
    finally:
        connection.close()
        close_thread_connections()
        reset_settings_cache()


@pytest.fixture
def client(web_db):
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


# -- signature -------------------------------------------------------------


def test_signature_matches_the_documented_hmac():
    body = b'{"a":1}'
    assert verify_signature(body, compute_signature(body, SECRET), SECRET)


def test_signature_is_computed_over_the_exact_bytes():
    """Reserialising the body would change the signature, which is why the endpoint reads raw
    bytes before parsing."""
    original = b'{"b":2,"a":1}'
    reserialised = json.dumps(json.loads(original)).encode()
    assert original != reserialised
    assert not verify_signature(reserialised, compute_signature(original, SECRET), SECRET)


def test_missing_or_wrong_signature_fails():
    body = b"{}"
    assert not verify_signature(body, None, SECRET)
    assert not verify_signature(body, "", SECRET)
    assert not verify_signature(body, "0" * 64, SECRET)
    assert not verify_signature(body, compute_signature(body, "other_secret"), SECRET)


def test_valid_signature_is_accepted(client, web_db):
    response = _post(client, _event(), event_id="evt_ok_1")
    assert response.status_code == 200
    assert response.json() == {
        "event_id": "evt_ok_1",
        "duplicate": False,
        "stale": False,
        "acted": True,
    }
    attempt = repo.get_attempt(web_db, "pay_test0000000001")
    assert attempt is not None
    assert attempt["status"] == "failed"
    assert attempt["upi_handle"] == "okhdfcbank"
    assert attempt["error_reason"] == "bank_technical_error"


def test_bad_signature_is_rejected_and_stores_nothing(client, web_db):
    response = _post(client, _event(), event_id="evt_bad_1", signature="deadbeef")
    assert response.status_code == 400
    assert repo.count_webhook_events(web_db) == 0
    assert repo.count_attempts(web_db) == 0


def test_missing_event_id_is_rejected(client, web_db):
    body = json.dumps(_event()).encode()
    response = client.post(
        "/api/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": compute_signature(body, SECRET)},
    )
    assert response.status_code == 400
    assert repo.count_webhook_events(web_db) == 0


def test_non_json_body_with_a_valid_signature_is_rejected(client, web_db):
    body = b"not json"
    response = client.post(
        "/api/webhooks/razorpay",
        content=body,
        headers={
            "X-Razorpay-Signature": compute_signature(body, SECRET),
            "X-Razorpay-Event-Id": "evt_junk",
        },
    )
    assert response.status_code == 400
    assert repo.count_webhook_events(web_db) == 0


# -- idempotency and ordering ---------------------------------------------


def test_duplicate_event_id_is_a_no_op(client, web_db):
    first = _post(client, _event(), event_id="evt_dup")
    second = _post(client, _event(payment={"status": "captured"}), event_id="evt_dup")
    assert first.status_code == second.status_code == 200
    assert second.json()["duplicate"] is True
    assert repo.count_webhook_events(web_db) == 1
    # The second body claimed captured; because the event id repeated, nothing was applied.
    assert repo.get_attempt(web_db, "pay_test0000000001")["status"] == "failed"


def test_out_of_order_capture_then_failure_is_safe(client, web_db):
    captured = _event("payment.captured", payment={"status": "captured"})
    _post(client, captured, event_id="evt_cap")
    _post(client, _event("payment.failed"), event_id="evt_fail")
    attempt = repo.get_attempt(web_db, "pay_test0000000001")
    order = repo.get_order(web_db, "order_test000000001")
    assert attempt["status"] == "captured"
    assert order["status"] == "paid"


def test_out_of_order_order_paid_then_failed_payment_keeps_the_order_paid(client, web_db):
    order_event = {
        "entity": "event",
        "event": "order.paid",
        "contains": ["order"],
        "created_at": 1785522600,
        "payload": {
            "order": {
                "entity": {
                    "id": "order_test000000001",
                    "entity": "order",
                    "amount": 250000,
                    "status": "paid",
                    "created_at": 1785522600,
                }
            }
        },
    }
    _post(client, _event("payment.failed"), event_id="evt_a")
    _post(client, order_event, event_id="evt_b")
    _post(client, _event("payment.failed", payment={"id": "pay_test0000000002"}), event_id="evt_c")
    assert repo.get_order(web_db, "order_test000000001")["status"] == "paid"


def test_unhandled_event_type_is_stored_but_not_acted_on(client, web_db):
    event = _event("payment.authorized")
    response = _post(client, event, event_id="evt_unhandled")
    assert response.status_code == 200
    assert response.json()["acted"] is False
    assert repo.count_webhook_events(web_db) == 1
    assert repo.count_attempts(web_db) == 0


def test_payment_link_event_without_a_case_is_a_recorded_no_op(client, web_db):
    event = {
        "entity": "event",
        "event": "payment_link.paid",
        "contains": ["payment_link"],
        "created_at": 1785522600,
        "payload": {"payment_link": {"entity": {"id": "plink_x", "status": "paid"}}},
    }
    response = _post(client, event, event_id="evt_link")
    assert response.status_code == 200
    assert repo.get_webhook_event(web_db, "evt_link")["acted"] == 1


# -- freshness -------------------------------------------------------------


def test_freshness_is_not_enforced_in_dev():
    settings = _settings(salvage_env="dev")
    old = {"created_at": 1000}
    assert not is_stale(old, 1000 + 10_000, settings)


def test_stale_event_in_demo_mode_is_stored_flagged_and_not_acted_on(conn):
    settings = _settings(salvage_env="demo")
    event = _event()
    body = json.dumps(event).encode()
    result = ingest_event(
        conn,
        event=event,
        event_id="evt_stale",
        raw_body=body,
        received_at=event["created_at"] + 3600,
        verified=True,
        settings=settings,
    )
    assert result.stale is True
    assert result.acted is False
    stored = repo.get_webhook_event(conn, "evt_stale")
    assert stored["stale"] == 1
    assert stored["acted"] == 0
    assert repo.count_attempts(conn) == 0


def test_fresh_event_in_demo_mode_is_acted_on(conn):
    settings = _settings(salvage_env="demo")
    event = _event()
    body = json.dumps(event).encode()
    result = ingest_event(
        conn,
        event=event,
        event_id="evt_fresh",
        raw_body=body,
        received_at=event["created_at"] + 60,
        verified=True,
        settings=settings,
    )
    assert result.stale is False
    assert result.acted is True


# -- ledger and PII --------------------------------------------------------


def test_every_verified_event_appends_one_ledger_entry(client, web_db):
    _post(client, _event(), event_id="evt_l1")
    _post(client, _event(payment={"id": "pay_test0000000009"}), event_id="evt_l2")
    _post(client, _event(), event_id="evt_l1")  # duplicate, no ledger entry
    kinds = [row["kind"] for row in web_db.execute("SELECT kind FROM ledger ORDER BY seq")]
    assert kinds == ["webhook.received", "webhook.received"]
    assert verify(web_db).ok


def test_the_ledger_entry_carries_no_contact_or_email(client, web_db):
    _post(client, _event(), event_id="evt_pii")
    payloads = " ".join(
        row["payload_json"] for row in web_db.execute("SELECT payload_json FROM ledger")
    )
    assert "+919876543210" not in payloads
    assert "someone@example.com" not in payloads
    # The raw body is still kept, in webhook_events.raw_json, which is never exported.
    assert "+919876543210" in repo.get_webhook_event(web_db, "evt_pii")["raw_json"]


def test_a_customer_is_created_for_an_unknown_order(client, web_db):
    _post(client, _event(), event_id="evt_newcust")
    attempt = repo.get_attempt(web_db, "pay_test0000000001")
    customer = repo.get_customer(web_db, attempt["customer_id"])
    assert customer["consent"] == 0  # never contact someone Salvage has never met
    assert len(customer["ref_hash"]) == 64


# -- dev-only replay route -------------------------------------------------


def test_replay_route_exists_in_dev(client):
    paths = _route_paths(client.app)
    assert "/api/webhooks/razorpay/replay" in paths


def test_replay_route_does_not_exist_in_demo(web_db, monkeypatch):
    monkeypatch.setenv("SALVAGE_ENV", "demo")
    reset_settings_cache()
    app = create_app()
    assert "/api/webhooks/razorpay/replay" not in _route_paths(app)
    with TestClient(app) as client:
        response = client.post(
            "/api/webhooks/razorpay/replay",
            content=b"{}",
            headers={"X-Razorpay-Event-Id": "e"},
        )
    assert response.status_code == 404


def _route_paths(app) -> set[str]:
    """FastAPI nests included routers, so walk them."""
    paths: set[str] = set()
    stack = list(app.routes)
    while stack:
        route = stack.pop()
        path = getattr(route, "path", None)
        if path:
            paths.add(path)
        stack.extend(getattr(route, "routes", []) or [])
        # FastAPI wraps an included router in a helper object rather than flattening its routes
        # into app.routes, so the wrapper has to be unwrapped to see the paths.
        for attribute in ("router", "original_router"):
            inner = getattr(route, attribute, None)
            if inner is not None:
                stack.extend(getattr(inner, "routes", []) or [])
    return paths


def test_health_route(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["env"] == "dev"


def test_time_is_not_frozen():
    """Guards against a fixture accidentally pinning time.time in a way that hides staleness."""
    assert time.time() > 1_700_000_000
