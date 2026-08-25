"""The normaliser is the one path both the simulator and the webhook receiver use."""

from __future__ import annotations

import json

import pytest

from salvage.ingest.normalize import (
    NormaliseError,
    normalize_order_from_payment,
    normalize_payment_entity,
)

# The payment.failed sample from razorpay.com/docs/webhooks/payloads/payments/, re-verified
# against the live page on 26 August 2026. It is a netbanking failure: the docs publish no
# payment.failed sample for UPI, and this fixture used to claim one by swapping method, vpa and
# bank into this payload and citing the docs for the result. That made the test circular, since
# the only authority for the shape was our own client.
RAZORPAY_NETBANKING_FAILED = {
    "id": "pay_DEAU825sJlCbGa",
    "entity": "payment",
    "amount": 50000,
    "currency": "INR",
    "status": "failed",
    "order_id": "order_DEATVTRRctwEGb",
    "method": "netbanking",
    "vpa": None,
    "bank": "HDFC",
    "error_code": "BAD_REQUEST_ERROR",
    "error_description": "Payment failed",
    "error_source": "bank",
    "error_step": "payment_authorization",
    "error_reason": "payment_failed",
    "acquirer_data": {"bank_transaction_id": None},
    "created_at": 1567610214,
}

# The payment entity sample from razorpay.com/docs/api/payments/entity/, verbatim from the live
# page on 26 August 2026, with email and contact removed because this project never stores them.
#
# Note what the card object does NOT carry: there is no `iin`. The documented keys are id, entity,
# name, last4, network, type, issuer, international, emi, sub_type and token_iin, and token_iin is
# null in the published sample. This fixture used to assert `"iin": "411111"` and cite this page
# for it. The consequence is recorded in docs/RESULTS.md: the detector's card_bin6 segment key has
# no source in the documented payment entity.
RAZORPAY_CARD_CAPTURED = {
    "id": "pay_L0nSsccovt6zyp",
    "entity": "payment",
    "amount": 9900,
    "currency": "INR",
    "status": "captured",
    "order_id": "order_L0nS83FfCHaWqV",
    "international": False,
    "method": "card",
    "card_id": "card_L0nSsfPv1LjA20",
    "card": {
        "id": "card_L0nSsfPv1LjA20",
        "entity": "card",
        "name": "",
        "last4": "0153",
        "network": "Visa",
        "type": "debit",
        "issuer": None,
        "international": False,
        "emi": False,
        "sub_type": "consumer",
        "token_iin": None,
    },
    "bank": None,
    "wallet": None,
    "vpa": None,
    "error_code": None,
    "error_description": None,
    "error_source": None,
    "error_step": None,
    "error_reason": None,
    "acquirer_data": {
        "auth_code": "299196",
        "authentication_reference_number": "100222021120200000000742753928",
    },
    "created_at": 1672987417,
}


def test_the_documented_failure_payload_maps_every_field():
    row = normalize_payment_entity(RAZORPAY_NETBANKING_FAILED, customer_id="cust_1")
    assert row["id"] == "pay_DEAU825sJlCbGa"
    assert row["order_id"] == "order_DEATVTRRctwEGb"
    assert row["customer_id"] == "cust_1"
    assert row["method"] == "netbanking"
    assert row["nb_bank"] == "HDFC"
    assert row["upi_handle"] is None
    assert row["status"] == "failed"
    assert row["error_code"] == "BAD_REQUEST_ERROR"
    assert row["error_source"] == "bank"
    assert row["error_step"] == "payment_authorization"
    assert row["error_reason"] == "payment_failed"
    assert row["error_description"] == "Payment failed"
    assert row["created_at"] == 1567610214
    assert row["truth_cause"] is None


def test_a_upi_failure_without_a_vpa_still_normalises():
    """The docs publish no payment.failed sample for UPI, and they warn twice that the vpa
    parameter may be absent on a UPI failure and must not be hardcoded. So the case the detector
    most depends on is the one the payload is least guaranteed to describe: with no vpa there is
    no upi_handle, and no upi_handle means no instrument-level segment key. The normaliser must at
    least not fall over, and docs/RESULTS.md records what it costs the detector."""
    entity = {**RAZORPAY_NETBANKING_FAILED, "method": "upi", "bank": None, "vpa": None}
    row = normalize_payment_entity(entity, customer_id="cust_1")
    assert row["method"] == "upi"
    assert row["upi_handle"] is None
    assert row["nb_bank"] is None
    assert row["error_reason"] == "payment_failed"


def test_card_entity_maps_network_and_type_but_has_no_bin_to_map():
    """The documented payment entity's card object carries no `iin`. It carries `token_iin`, null
    in the published sample and populated only for a network token, which is not the real card's
    BIN. card_bin is therefore None for a payload that came from Razorpay as documented."""
    row = normalize_payment_entity(RAZORPAY_CARD_CAPTURED, customer_id="cust_2")
    assert row["card_network"] == "Visa"
    assert row["card_issuer"] is None
    assert row["card_bin"] is None
    assert row["status"] == "captured"
    assert row["upi_handle"] is None


def test_raw_json_preserves_the_entity_verbatim():
    row = normalize_payment_entity(RAZORPAY_CARD_CAPTURED, customer_id="cust_2")
    assert json.loads(row["raw_json"]) == RAZORPAY_CARD_CAPTURED


def test_unknown_error_values_are_kept_not_dropped():
    entity = {
        **RAZORPAY_NETBANKING_FAILED,
        "error_source": "a_source_razorpay_added_in_2027",
        "error_step": "payment_teleportation",
        "error_reason": "brand_new_reason",
    }
    row = normalize_payment_entity(entity, customer_id="c")
    assert row["error_source"] == "a_source_razorpay_added_in_2027"
    assert row["error_step"] == "payment_teleportation"
    assert row["error_reason"] == "brand_new_reason"


def test_vpa_without_an_at_sign_yields_no_handle():
    entity = {**RAZORPAY_NETBANKING_FAILED, "method": "upi", "vpa": "notavpa"}
    assert normalize_payment_entity(entity, customer_id="c")["upi_handle"] is None


def test_wallet_instrument_lands_in_the_same_column_as_the_bank_code():
    entity = {
        "id": "pay_w",
        "order_id": "order_w",
        "method": "wallet",
        "wallet": "phonepe",
        "status": "failed",
        "amount": 1000,
        "created_at": 10,
    }
    assert normalize_payment_entity(entity, customer_id="c")["nb_bank"] == "phonepe"


def test_missing_required_fields_raise():
    with pytest.raises(NormaliseError):
        normalize_payment_entity({"order_id": "o", "method": "upi"}, customer_id="c")
    with pytest.raises(NormaliseError):
        normalize_payment_entity({"id": "p", "method": "upi"}, customer_id="c")
    with pytest.raises(NormaliseError):
        normalize_payment_entity({"id": "p", "order_id": "o"}, customer_id="c")


def test_order_row_from_a_captured_payment_is_paid():
    order = normalize_order_from_payment(
        RAZORPAY_CARD_CAPTURED, customer_id="cust_2", source="razorpay"
    )
    assert order["status"] == "paid"
    assert order["paid_at"] == 1672987417
    assert order["amount"] == 9900
    assert order["source"] == "razorpay"


def test_order_row_from_a_failed_payment_is_attempted():
    order = normalize_order_from_payment(
        RAZORPAY_NETBANKING_FAILED, customer_id="cust_1", source="razorpay"
    )
    assert order["status"] == "attempted"
    assert order["paid_at"] is None
