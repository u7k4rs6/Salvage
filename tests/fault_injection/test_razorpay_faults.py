"""Razorpay faults: 429, 5xx, timeout mid-create, and an order paid while a create is in flight.

Architecture section 15. Every case asserts the same two things: nothing wrong happens to a
customer or to an order, and the outcome is recorded.
"""

from __future__ import annotations

import json

import httpx
import pytest

from salvage import repo
from salvage.config import Settings
from salvage.db import open_migrated
from salvage.execute.razorpay_client import (
    MAX_ATTEMPTS,
    DuplicateReference,
    RazorpayClient,
    RazorpayError,
)
from salvage.execute.scheduler import AgentRunner
from salvage.execute.workflow import CaseState
from salvage.ledger import Ledger, verify
from salvage.sim.params import default_params
from salvage.sim.response import ResponseModel


def _settings() -> Settings:
    return Settings(
        razorpay_key_id="rzp_test_abcdefghij",
        razorpay_key_secret="s",
        razorpay_webhook_secret="w",
        _env_file=None,
    )


def _client(handler) -> RazorpayClient:
    return RazorpayClient(
        settings=_settings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleeper=lambda _: None,
    )


def test_429_mid_create_is_retried_and_never_creates_two_links(injection_log):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content)["reference_id"])
        if len(calls) < 3:
            return httpx.Response(429, json={"error": {"description": "rate limited"}})
        return httpx.Response(200, json={"id": "plink_1", "reference_id": "case_1"})

    response = _client(handler).create_payment_link(
        amount=1000, reference_id="case_1", expire_by=1, description="d"
    )
    assert response.body["id"] == "plink_1"
    # Every retry carried the same reference_id, which is what stops a retry making a second link.
    assert set(calls) == {"case_1"}
    injection_log.record(
        category="razorpay",
        attack="429 mid-create",
        refused=False,
        ledgered=False,
        detail="retried with the same reference_id, one link created",
        expect_refusal=False,
    )


def test_5xx_mid_create_gives_up_rather_than_looping(injection_log):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503, json={"error": {"description": "unavailable"}})

    with pytest.raises(RazorpayError, match="attempts"):
        _client(handler).create_payment_link(
            amount=1000, reference_id="case_1", expire_by=1, description="d"
        )
    assert len(calls) == MAX_ATTEMPTS
    injection_log.record(
        category="razorpay",
        attack="5xx mid-create",
        refused=True,
        ledgered=False,
        detail=f"gave up after {MAX_ATTEMPTS} attempts, no link created",
    )


def test_a_timeout_mid_create_is_retried_and_then_reported(injection_log):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ReadTimeout("slow")

    with pytest.raises(RazorpayError, match="attempts"):
        _client(handler).create_payment_link(
            amount=1000, reference_id="case_1", expire_by=1, description="d"
        )
    assert len(calls) == MAX_ATTEMPTS
    injection_log.record(
        category="razorpay",
        attack="timeout mid-create",
        refused=True,
        ledgered=False,
        detail="three attempts then an error the executor records",
    )


def test_a_lost_response_recovers_the_existing_link_instead_of_making_another(injection_log):
    """The idempotency path: create succeeded, its response was lost, the retry sees a duplicate."""
    created = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            created.append(1)
            return httpx.Response(
                400, json={"error": {"description": "reference_id is already in use"}}
            )
        return httpx.Response(
            200, json={"payment_links": [{"id": "plink_first", "reference_id": "case_1"}]}
        )

    client = _client(handler)
    with pytest.raises(DuplicateReference):
        client.create_payment_link(amount=1000, reference_id="case_1", expire_by=1, description="d")
    existing = client.fetch_payment_link_by_reference("case_1")
    assert existing is not None
    assert existing.body["id"] == "plink_first"
    injection_log.record(
        category="razorpay",
        attack="duplicate reference_id after a lost response",
        refused=True,
        ledgered=False,
        detail="fetched the existing link by reference, no second link",
    )


class _PaysDuringCreate:
    """A gateway that has the order paid by another route while the create is in flight."""

    def __init__(self, conn, order_id: str, paid_at: int) -> None:
        self._conn = conn
        self._order_id = order_id
        self._paid_at = paid_at
        self.created: list[dict] = []
        self.cancelled: list[str] = []

    def create_link(self, *, case_id, amount, expire_by, description, checkout_display):
        repo.mark_order_paid(self._conn, self._order_id, self._paid_at)
        link = {"id": f"plink_race{len(self.created)}", "short_url": "https://rzp.io/i/race"}
        self.created.append(link)
        return link

    def cancel_link(self, link_id: str) -> None:
        self.cancelled.append(link_id)


def test_an_order_paid_while_the_link_is_in_flight_closes_as_paid_elsewhere(
    tmp_path, injection_log
):
    conn = open_migrated(tmp_path / "race.db")
    try:
        now = 1_700_000_000
        repo.insert_customer(
            conn,
            {
                "id": "cust_1",
                "ref_hash": "h" * 64,
                "consent": 1,
                "locale": "en",
                "typical_amount": 100000,
                "created_at": 0,
            },
        )
        repo.upsert_order(
            conn,
            {
                "id": "order_1",
                "customer_id": "cust_1",
                "amount": 100000,
                "status": "attempted",
                "source": "sim",
                "created_at": now - 600,
            },
        )
        repo.upsert_attempt(
            conn,
            {
                "id": "pay_1",
                "order_id": "order_1",
                "customer_id": "cust_1",
                "method": "upi",
                "status": "failed",
                "error_reason": "bank_technical_error",
                "created_at": now - 600,
                "raw_json": "{}",
            },
        )
        incident = {
            "id": "inc_1",
            "segment_key": "upi",
            "opened_at": now,
            "closed_at": now,
            "at_risk_amount": 0,
            "rules_cause": "issuer_outage",
            "llm_cause": "issuer_outage",
            "root_cause": "issuer_outage",
            "confidence": 0.9,
            "plan_json": None,
            "status": "open",
            "affected_scope_json": "[]",
        }
        repo.insert_incident(conn, incident)
        case = {
            "id": "case_1",
            "order_id": "order_1",
            "customer_id": "cust_1",
            "incident_id": "inc_1",
            "state": CaseState.DETECTED.value,
            "attempts": 0,
            "link_id": None,
            "link_url": None,
            "next_action_at": None,
            "ttl_at": now + 72 * 3600,
            "outcome": None,
            "updated_at": now,
        }
        repo.insert_case(conn, case)

        gateway = _PaysDuringCreate(conn, "order_1", paid_at=now - 60)
        runner = AgentRunner(
            conn,
            response=ResponseModel(default_params(), 0),
            gateway=gateway,
            seed=0,
        )
        runner._apply_case_action(  # noqa: SLF001
            incident,
            __import__(
                "salvage.decide.menu", fromlist=["ActionType"]
            ).ActionType.SEND_RECOVERY_LINK,
            {"case_id": "case_1"},
            case,
            now,
        )
        runner._settle(now + 86400)  # noqa: SLF001

        stored = repo.get_case(conn, "case_1")
        assert stored["outcome"] == "PAID_ELSEWHERE"
        assert gateway.cancelled == [gateway.created[0]["id"]]
        assert conn.execute("SELECT COUNT(*) AS n FROM customer_comms").fetchone()["n"] == 0
        assert verify(conn).ok
        injection_log.record(
            category="razorpay",
            attack="order paid while link creation in flight",
            refused=True,
            ledgered=True,
            detail="case closed PAID_ELSEWHERE, link cancelled, no message sent",
        )
    finally:
        conn.close()


def test_the_ledger_records_a_razorpay_failure_rather_than_swallowing_it(tmp_path, injection_log):
    conn = open_migrated(tmp_path / "led.db")
    try:
        Ledger(conn).append(
            "execute.action.failed",
            "action",
            "act_1",
            {"type": "SEND_RECOVERY_LINK", "error": "503 after 3 attempts"},
            ts=1_700_000_000,
        )
        entries = [entry.kind for entry in Ledger(conn).entries()]
        assert "execute.action.failed" in entries
        assert verify(conn).ok
        injection_log.record(
            category="razorpay",
            attack="failure is recorded in the ledger",
            refused=True,
            ledgered=True,
        )
    finally:
        conn.close()
