"""Razorpay client: retry classification, idempotency, and the documented request shape.

httpx.MockTransport throughout, so no socket is opened. CI runs this with no credentials beyond
the placeholder key pair the fixture supplies.
"""

from __future__ import annotations

import json

import httpx
import pytest

from salvage.config import Settings
from salvage.execute.razorpay_client import (
    MAX_ATTEMPTS,
    DuplicateReference,
    RazorpayClient,
    RazorpayError,
)


def _settings() -> Settings:
    return Settings(
        razorpay_key_id="rzp_test_abcdefghij",
        razorpay_key_secret="secret",
        razorpay_webhook_secret="w",
        _env_file=None,
    )


def _client(handler) -> RazorpayClient:
    return RazorpayClient(
        settings=_settings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleeper=lambda _: None,
    )


def test_a_live_key_id_is_refused_before_any_call():
    settings = Settings(
        razorpay_key_id="",
        razorpay_key_secret="s",
        razorpay_webhook_secret="w",
        _env_file=None,
    )
    with pytest.raises(Exception, match="RAZORPAY_KEY_ID"):
        RazorpayClient(settings=settings, client=httpx.Client())


def test_the_create_link_body_matches_the_documented_shape():
    """Fields checked against razorpay.com/docs/api/payments/payment-links/create-standard/."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "plink_1", "short_url": "https://rzp.io/i/x"})

    client = _client(handler)
    client.create_payment_link(
        amount=250000,
        reference_id="case_abc",
        expire_by=1_800_000_000,
        description="Recovery link",
    )
    assert seen["method"] == "POST"
    assert seen["url"].endswith("/v1/payment_links")
    body = seen["body"]
    assert body["amount"] == 250000
    assert body["currency"] == "INR"
    assert body["reference_id"] == "case_abc"
    assert body["expire_by"] == 1_800_000_000
    assert body["accept_partial"] is False
    # Architecture section 12: notify flags are false in every environment.
    assert body["notify"] == {"sms": False, "email": False}
    assert body["reminder_enable"] is False
    # No discount, no partial amount, nothing that could change what is owed.
    assert "first_min_partial_amount" not in body


def test_a_reference_id_longer_than_forty_characters_is_truncated():
    """Razorpay documents a 40 character limit on reference_id."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "plink_1"})

    _client(handler).create_payment_link(
        amount=100, reference_id="x" * 80, expire_by=1, description="d"
    )
    assert len(seen["body"]["reference_id"]) == 40


def test_the_checkout_display_config_is_nested_where_razorpay_documents_it():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "plink_1"})

    _client(handler).create_payment_link(
        amount=100,
        reference_id="c",
        expire_by=1,
        description="d",
        checkout_display={"hide": [{"method": "card"}]},
    )
    assert seen["body"]["options"]["checkout"]["config"]["display"] == {
        "hide": [{"method": "card"}]
    }


# -- retry classification --------------------------------------------------


def test_a_429_is_retried():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(429, json={"error": {"description": "rate limited"}})
        return httpx.Response(200, json={"id": "plink_1"})

    assert (
        _client(handler)
        .create_payment_link(amount=1, reference_id="c", expire_by=1, description="d")
        .body["id"]
        == "plink_1"
    )
    assert len(calls) == 3


def test_a_5xx_is_retried_then_gives_up():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(502, json={"error": {"description": "bad gateway"}})

    with pytest.raises(RazorpayError, match=f"after {MAX_ATTEMPTS} attempts"):
        _client(handler).fetch_order("order_1")
    assert len(calls) == MAX_ATTEMPTS


def test_a_timeout_is_retried():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ReadTimeout("slow")

    with pytest.raises(RazorpayError, match="attempts"):
        _client(handler).fetch_order("order_1")
    assert len(calls) == MAX_ATTEMPTS


def test_a_400_is_not_retried():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(400, json={"error": {"description": "amount is invalid"}})

    with pytest.raises(RazorpayError, match="amount is invalid"):
        _client(handler).fetch_order("order_1")
    assert len(calls) == 1


# -- idempotency -----------------------------------------------------------


def test_a_duplicate_reference_is_its_own_exception_not_a_generic_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "description": "The reference_id has already been used for another link",
                }
            },
        )

    with pytest.raises(DuplicateReference):
        _client(handler).create_payment_link(
            amount=1, reference_id="case_1", expire_by=1, description="d"
        )


def test_a_duplicate_reference_is_recoverable_by_fetching_the_existing_link():
    """The idempotency path: a create whose response was lost never makes a second link."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                400, json={"error": {"description": "reference_id is already in use"}}
            )
        return httpx.Response(
            200, json={"payment_links": [{"id": "plink_existing", "reference_id": "case_1"}]}
        )

    client = _client(handler)
    with pytest.raises(DuplicateReference):
        client.create_payment_link(amount=1, reference_id="case_1", expire_by=1, description="d")
    existing = client.fetch_payment_link_by_reference("case_1")
    assert existing is not None
    assert existing.body["id"] == "plink_existing"


def test_an_ordinary_400_is_not_mistaken_for_a_duplicate_reference():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"description": "amount must be at least 100"}})

    with pytest.raises(RazorpayError) as info:
        _client(handler).create_payment_link(
            amount=1, reference_id="c", expire_by=1, description="d"
        )
    assert not isinstance(info.value, DuplicateReference)


def test_the_request_id_header_is_captured_for_the_ledger():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"id": "order_1"}, headers={"x-razorpay-request-id": "req_abc"}
        )

    assert _client(handler).fetch_order("order_1").request_id == "req_abc"
