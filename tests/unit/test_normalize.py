"""The normaliser is the one path both the simulator and the webhook receiver use."""

from __future__ import annotations

import json

import pytest

from salvage.ingest.normalize import (
    NormaliseError,
    normalize_order_from_payment,
    normalize_payment_entity,
)

# A payment.failed payment entity, field for field from
# razorpay.com/docs/webhooks/payloads/payments/ (fetched 24 August 2026), with the card and vpa
# fields from razorpay.com/docs/api/payments/entity/.
RAZORPAY_UPI_FAILED = {
    "id": "pay_DEAU825sJlCbGa",
    "entity": "payment",
    "amount": 50000,
    "currency": "INR",
    "status": "failed",
    "order_id": "order_DEATVTRRctwEGb",
    "method": "upi",
    "vpa": "gauravkumar@exampleupi",
    "bank": "UTIB",
    "error_code": "BAD_REQUEST_ERROR",
    "error_description": "Payment failed",
    "error_source": "bank",
    "error_step": "payment_authorization",
    "error_reason": "payment_failed",
    "acquirer_data": {"bank_transaction_id": None},
    "created_at": 1567610214,
}

RAZORPAY_CARD_CAPTURED = {
    "id": "pay_29QQoUBi66xm2f",
    "entity": "payment",
    "amount": 100000,
    "currency": "INR",
    "status": "captured",
    "order_id": "order_GjCr5oKh4AVC51",
    "method": "card",
    "card": {
        "id": "card_JXPULjlKqC5j0i",
        "entity": "card",
        "name": "Gaurav",
        "last4": "1111",
        "network": "Visa",
        "type": "debit",
        "issuer": "HDFC",
        "iin": "411111",
        "international": False,
        "sub_type": "consumer",
    },
    "created_at": 1567610214,
}


def test_upi_entity_maps_every_field():
    row = normalize_payment_entity(RAZORPAY_UPI_FAILED, customer_id="cust_1")
    assert row["id"] == "pay_DEAU825sJlCbGa"
    assert row["order_id"] == "order_DEATVTRRctwEGb"
    assert row["customer_id"] == "cust_1"
    assert row["method"] == "upi"
    assert row["upi_handle"] == "exampleupi"
    assert row["nb_bank"] == "UTIB"
    assert row["status"] == "failed"
    assert row["error_code"] == "BAD_REQUEST_ERROR"
    assert row["error_source"] == "bank"
    assert row["error_step"] == "payment_authorization"
    assert row["error_reason"] == "payment_failed"
    assert row["error_description"] == "Payment failed"
    assert row["created_at"] == 1567610214
    assert row["truth_cause"] is None


def test_card_entity_maps_network_issuer_and_iin():
    row = normalize_payment_entity(RAZORPAY_CARD_CAPTURED, customer_id="cust_2")
    assert row["card_bin"] == "411111"
    assert row["card_network"] == "Visa"
    assert row["card_issuer"] == "HDFC"
    assert row["status"] == "captured"
    assert row["upi_handle"] is None


def test_raw_json_preserves_the_entity_verbatim():
    row = normalize_payment_entity(RAZORPAY_CARD_CAPTURED, customer_id="cust_2")
    assert json.loads(row["raw_json"]) == RAZORPAY_CARD_CAPTURED


def test_unknown_error_values_are_kept_not_dropped():
    entity = {
        **RAZORPAY_UPI_FAILED,
        "error_source": "a_source_razorpay_added_in_2027",
        "error_step": "payment_teleportation",
        "error_reason": "brand_new_reason",
    }
    row = normalize_payment_entity(entity, customer_id="c")
    assert row["error_source"] == "a_source_razorpay_added_in_2027"
    assert row["error_step"] == "payment_teleportation"
    assert row["error_reason"] == "brand_new_reason"


def test_vpa_without_an_at_sign_yields_no_handle():
    entity = {**RAZORPAY_UPI_FAILED, "vpa": "notavpa"}
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
    assert order["paid_at"] == 1567610214
    assert order["amount"] == 100000
    assert order["source"] == "razorpay"


def test_order_row_from_a_failed_payment_is_attempted():
    order = normalize_order_from_payment(
        RAZORPAY_UPI_FAILED, customer_id="cust_1", source="razorpay"
    )
    assert order["status"] == "attempted"
    assert order["paid_at"] is None
