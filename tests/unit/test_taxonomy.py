"""The Razorpay error taxonomy is transcribed, not invented."""

from __future__ import annotations

from salvage import taxonomy


def test_reason_list_is_complete_and_unique():
    # 110 rows in Razorpay's downloadable payments_error_reasons.xlsx, deduplicated.
    assert len(taxonomy.ERROR_REASONS) == 110
    assert len(set(taxonomy.ERROR_REASONS)) == 110
    assert list(taxonomy.ERROR_REASONS) == sorted(taxonomy.ERROR_REASONS)


def test_sources_and_steps_cover_every_modelled_method():
    for method in ("upi", "card", "netbanking", "wallet"):
        assert taxonomy.SOURCES_BY_METHOD[method]
        assert taxonomy.STEPS_BY_METHOD[method]


def test_published_values_are_recognised():
    assert taxonomy.is_known_source("issuer_bank")
    assert taxonomy.is_known_step("payment_authentication")
    assert taxonomy.is_known_reason("insufficient_funds")
    assert taxonomy.is_known_code("GATEWAY_ERROR")


def test_unknown_values_pass_through_rather_than_raise():
    # Razorpay's own payment.failed webhook sample carries error_source "bank", which its
    # per-method source lists publish only for Emandate. Passthrough is required behaviour.
    assert taxonomy.coerce_source("bank") == "bank"
    assert taxonomy.coerce_source("something_new_2027") == "something_new_2027"
    assert taxonomy.coerce_step("payment_teleportation") == "payment_teleportation"
    assert taxonomy.coerce_reason("brand_new_reason") == "brand_new_reason"
    assert taxonomy.coerce_source(None) is None
    assert not taxonomy.is_known_source("something_new_2027")


def test_error_code_pairing_matches_the_published_grouping():
    assert taxonomy.error_code_for_reason("bank_technical_error") == "GATEWAY_ERROR"
    assert taxonomy.error_code_for_reason("insufficient_funds") == "BAD_REQUEST_ERROR"
    assert taxonomy.error_code_for_reason("not_a_real_reason") == "BAD_REQUEST_ERROR"


def test_hard_declines_are_a_subset_of_published_reasons():
    assert set(taxonomy.ERROR_REASONS) >= taxonomy.HARD_DECLINE_REASONS
    assert taxonomy.is_hard_decline("debit_instrument_blocked")
    assert not taxonomy.is_hard_decline("insufficient_funds")
