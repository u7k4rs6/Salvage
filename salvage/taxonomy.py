"""Razorpay error taxonomy, pulled from the official documentation.

Sources used, all fetched 24 August 2026:
  https://razorpay.com/docs/errors/
  https://razorpay.com/docs/errors/payment-error-parameters
    (also served at /docs/errors/payments/payment-methods-error-parameters/)
  https://razorpay.com/docs/errors/payments/list/
  https://razorpay.com/docs/errors/payments/cards/
  https://razorpay.com/docs/errors/payments/upi/
  https://razorpay.com/docs/api/payments/entity/
  https://razorpay.com/docs/webhooks/payloads/payments/
  https://razorpay.com/docs/build/browser/assets/images/payments_error_reasons.xlsx
    (the "Download list of possible error reasons" sheet linked from the errors pages)

Three fields describe a Razorpay payment failure and the docs are explicit about the division:
source is who failed, step is where in the flow it failed, reason is why.

Everything below is transcribed from those pages. Where Razorpay does not publish a value we do
not invent one: see UNKNOWN_IS_ALLOWED. Every enum here is open. `coerce_*` returns the enum member
for a known value and passes an unknown string through unchanged, because Razorpay ships values
that are not in its own published lists. One example is in Razorpay's own webhook payload sample
for payment.failed, which carries "error_source": "bank" although "bank" appears in the published
source list only for Emandate. Passthrough is therefore required behaviour, not defensive coding.
"""

from __future__ import annotations

from enum import StrEnum

# ---------------------------------------------------------------------------
# error_code. Top-level classification on the payment entity.
# https://razorpay.com/docs/errors/ and /docs/errors/payments/list/
# ---------------------------------------------------------------------------


class ErrorCode(StrEnum):
    BAD_REQUEST_ERROR = "BAD_REQUEST_ERROR"
    GATEWAY_ERROR = "GATEWAY_ERROR"
    SERVER_ERROR = "SERVER_ERROR"


# ---------------------------------------------------------------------------
# error_source. Published per payment method, see the error parameters page.
# ---------------------------------------------------------------------------


class ErrorSource(StrEnum):
    CUSTOMER = "customer"
    BUSINESS = "business"
    INTERNAL = "internal"
    GATEWAY = "gateway"
    ISSUER_BANK = "issuer_bank"
    ISSUER = "issuer"
    NETWORK = "network"
    CUSTOMER_PSP = "customer_psp"
    BENEFICIARY_BANK = "beneficiary_bank"
    BANK = "bank"


SOURCES_BY_METHOD: dict[str, tuple[str, ...]] = {
    "card": ("customer", "business", "internal", "gateway", "issuer_bank"),
    "upi": (
        "customer",
        "business",
        "internal",
        "customer_psp",
        "gateway",
        "network",
        "issuer_bank",
        "beneficiary_bank",
    ),
    "netbanking": ("customer", "business", "internal", "issuer_bank"),
    "wallet": ("customer", "business", "internal", "issuer"),
    "cardless_emi": ("customer", "business", "internal", "network", "issuer"),
    "emandate": ("customer", "bank", "business", "internal", "gateway", "issuer_bank"),
}


# ---------------------------------------------------------------------------
# error_step. Published per payment method as the stages of that method's flow.
# ---------------------------------------------------------------------------


class ErrorStep(StrEnum):
    PAYMENT_INITIATION = "payment_initiation"
    PAYMENT_CREATION = "payment_creation"
    PAYMENT_ELIGIBILITY_CHECK = "payment_eligibility_check"
    PAYMENT_AUTHENTICATION = "payment_authentication"
    PAYMENT_AUTHORIZATION = "payment_authorization"
    PAYMENT_CAPTURE = "payment_capture"
    PAYMENT_REQUEST = "payment_request"
    PAYMENT_RESPONSE = "payment_response"
    PAYMENT_DEBIT_REQUEST = "payment_debit_request"
    PAYMENT_DEBIT_RESPONSE = "payment_debit_response"
    PAYMENT_CREDIT_REQUEST = "payment_credit_request"
    PAYMENT_CREDIT_RESPONSE = "payment_credit_response"
    PAYMENT_STATUS_REQUEST = "payment_status_request"
    PAYMENT_STATUS_RESPONSE = "payment_status_response"


STEPS_BY_METHOD: dict[str, tuple[str, ...]] = {
    "card": (
        "payment_initiation",
        "payment_authentication",
        "payment_authorization",
        "payment_capture",
    ),
    "netbanking": ("payment_initiation", "payment_authentication", "payment_authorization"),
    "wallet": (
        "payment_initiation",
        "payment_eligibility_check",
        "payment_authentication",
        "payment_authorization",
    ),
    "cardless_emi": (
        "payment_initiation",
        "payment_eligibility_check",
        "payment_authentication",
        "payment_authorization",
    ),
    "emandate": ("payment_initiation", "payment_authentication", "payment_authorization"),
    # UPI is published as two flows. Salvage models UPI Intent, because Razorpay is deprecating
    # UPI Collect from 28 February 2026 (stated on the error parameters page).
    "upi": (
        "payment_initiation",
        "payment_creation",
        "payment_authentication",
        "payment_request",
        "payment_debit_request",
        "payment_debit_response",
        "payment_credit_request",
        "payment_credit_response",
        "payment_status_request",
        "payment_status_response",
        "payment_response",
    ),
}


# ---------------------------------------------------------------------------
# error_reason. The complete published list, transcribed from the downloadable
# payments_error_reasons.xlsx sheet (110 rows) and cross-checked against
# /docs/errors/payments/list/, which groups the same reasons under BAD_REQUEST_ERROR and
# GATEWAY_ERROR. The sheet ships one row with a stray space, "psp_app_ not_available"; the list
# page spells it "psp_app_not_available", so that spelling is used here and the typo is recorded
# in docs/BUILD_LOG.md.
# ---------------------------------------------------------------------------

ERROR_REASONS: tuple[str, ...] = (
    "amount_less_than_minimum_amount",
    "authentication_failed",
    "authorisation_declined_by_psp",
    "bank_account_invalid",
    "bank_account_validation_failed",
    "bank_cutoff_in_progress",
    "bank_not_available",
    "bank_not_enabled",
    "bank_technical_error",
    "beneficiary_account_does_not_exist",
    "beneficiary_account_dormant",
    "capture_failed",
    "card_declined",
    "card_expired",
    "card_network_not_enabled",
    "card_not_enrolled",
    "card_number_invalid",
    "card_type_invalid",
    "collect_on_mcc_blocked",
    "collect_request_pending",
    "compliance_violation",
    "credit_failed",
    "credit_limit_exceeded",
    "credit_limit_expired",
    "credit_limit_inactive",
    "credit_limit_not_approved",
    "credit_not_permitted",
    "debit_declined",
    "debit_instrument_blocked",
    "debit_instrument_inactive",
    "deemed_transaction",
    "duplicate_refund_id",
    "duplicate_request",
    "duplicate_rrn_found",
    "emi_greater_than_max_amount",
    "emi_plan_unavailable",
    "funds_blocked_by_mandate",
    "gateway_technical_error",
    "incorrect_atm_pin",
    "incorrect_card_details",
    "incorrect_card_expiry_date",
    "incorrect_cardholder_name",
    "incorrect_cvv",
    "incorrect_otp",
    "incorrect_pin",
    "input_validation_failed",
    "insufficient_funds",
    "international_transaction_not_allowed",
    "invalid_amount",
    "invalid_currency",
    "invalid_device",
    "invalid_email",
    "invalid_mobile_number",
    "invalid_order_id",
    "invalid_request",
    "invalid_response_from_gateway",
    "invalid_user_details",
    "invalid_vpa",
    "issuer_technical_error",
    "live_mode_not_enabled",
    "mandate_creation_declined",
    "mandate_creation_expired",
    "mandate_creation_failed",
    "mandate_creation_timeout",
    "mcc_amount_limit_exceeded",
    "merchant_not_activated",
    "mismatch_in_transaction_details",
    "mobile_number_invalid",
    "order_already_paid",
    "order_amount_mismatch",
    "order_payment_method_mismatch",
    "otp_attempts_exceeded",
    "otp_expired",
    "payment_amount_tampered",
    "payment_cancelled",
    "payment_collect_request_expired",
    "payment_declined",
    "payment_declined_due_to_high_traffic",
    "payment_failed",
    "payment_method_not_enabled",
    "payment_pending",
    "payment_pending_approval",
    "payment_risk_check_failed",
    "payment_session_expired",
    "payment_timed_out",
    "pin_attempts_exceeded",
    "pin_not_set",
    "psp_app_not_available",
    "psp_app_not_supported",
    "psp_not_available",
    "psp_not_registered",
    "record_not_found",
    "recurring_payment_not_enabled",
    "refund_limit_crossed",
    "reqauth_mandate_not_acknowledged",
    "request_timed_out",
    "server_error",
    "transaction_daily_count_exceeded",
    "transaction_daily_limit_exceeded",
    "transaction_frequency_limit_exceeded",
    "transaction_limit_exceeded",
    "transaction_on_vpa_restricted",
    "upi_app_technical_error",
    "upi_autopay_not_supported_on_psp",
    "upi_collect_not_enabled",
    "upi_intent_not_enabled",
    "user_not_eligible",
    "user_not_registered_for_netbanking",
    "verification_failed",
    "vpa_resolution_failed",
)

ErrorReason = StrEnum("ErrorReason", {r.upper(): r for r in ERROR_REASONS})

# Which top-level error_code Razorpay pairs each reason with, from /docs/errors/payments/list/.
# A reason listed in both sections is a genuine overlap on that page, not a transcription error;
# GATEWAY_ERROR wins here because a payment that reaches the gateway is the case Salvage cares
# about, and the choice is recorded in docs/BUILD_LOG.md.
_GATEWAY_REASONS = frozenset(
    {
        "authentication_failed",
        "authorisation_declined_by_psp",
        "bank_cutoff_in_progress",
        "bank_not_available",
        "bank_technical_error",
        "beneficiary_account_does_not_exist",
        "beneficiary_account_dormant",
        "card_declined",
        "collect_on_mcc_blocked",
        "collect_request_pending",
        "credit_failed",
        "credit_limit_exceeded",
        "credit_limit_expired",
        "credit_limit_inactive",
        "credit_limit_not_approved",
        "credit_not_permitted",
        "debit_declined",
        "debit_instrument_blocked",
        "debit_instrument_inactive",
        "deemed_transaction",
        "duplicate_rrn_found",
        "funds_blocked_by_mandate",
        "gateway_technical_error",
        "invalid_response_from_gateway",
        "invalid_vpa",
        "issuer_technical_error",
        "mandate_creation_declined",
        "mandate_creation_expired",
        "mandate_creation_failed",
        "mandate_creation_timeout",
        "mcc_amount_limit_exceeded",
        "payment_amount_tampered",
        "payment_cancelled",
        "payment_collect_request_expired",
        "payment_declined",
        "payment_declined_due_to_high_traffic",
        "payment_failed",
        "payment_pending",
        "payment_risk_check_failed",
        "payment_session_expired",
        "payment_timed_out",
        "psp_app_not_available",
        "psp_app_not_supported",
        "psp_not_available",
        "psp_not_registered",
        "reqauth_mandate_not_acknowledged",
        "request_timed_out",
        "server_error",
        "transaction_daily_count_exceeded",
        "transaction_daily_limit_exceeded",
        "transaction_frequency_limit_exceeded",
        "user_not_eligible",
        "vpa_resolution_failed",
    }
)


def error_code_for_reason(reason: str) -> str:
    """The error_code Razorpay pairs with a reason. Unknown reasons get BAD_REQUEST_ERROR,
    which is what the docs use for everything not classed as a gateway failure."""
    if reason in _GATEWAY_REASONS:
        return ErrorCode.GATEWAY_ERROR.value
    return ErrorCode.BAD_REQUEST_ERROR.value


# ---------------------------------------------------------------------------
# Open enums. Razorpay ships values outside its own published lists, so every one of these
# coerce functions passes an unknown value through instead of raising.
# ---------------------------------------------------------------------------

_KNOWN_SOURCES = frozenset(s.value for s in ErrorSource)
_KNOWN_STEPS = frozenset(s.value for s in ErrorStep)
_KNOWN_REASONS = frozenset(ERROR_REASONS)
_KNOWN_CODES = frozenset(c.value for c in ErrorCode)

UNKNOWN_IS_ALLOWED = True


def coerce_source(value: str | None) -> str | None:
    return value


def coerce_step(value: str | None) -> str | None:
    return value


def coerce_reason(value: str | None) -> str | None:
    return value


def is_known_source(value: str | None) -> bool:
    return value in _KNOWN_SOURCES


def is_known_step(value: str | None) -> bool:
    return value in _KNOWN_STEPS


def is_known_reason(value: str | None) -> bool:
    return value in _KNOWN_REASONS


def is_known_code(value: str | None) -> bool:
    return value in _KNOWN_CODES


# ---------------------------------------------------------------------------
# Hard declines. docs/01_PRD.md section 9: card blocked, account closed, suspected fraud and
# invalid instrument get no retry and no link. Mapped onto published reasons.
# Used by the policy engine in M2; defined here so there is one list, not several.
# ---------------------------------------------------------------------------

HARD_DECLINE_REASONS: frozenset[str] = frozenset(
    {
        "debit_instrument_blocked",
        "debit_instrument_inactive",
        "card_expired",
        "card_number_invalid",
        "card_type_invalid",
        "bank_account_invalid",
        "beneficiary_account_does_not_exist",
        "beneficiary_account_dormant",
        "payment_risk_check_failed",
        "compliance_violation",
        "invalid_vpa",
        "invalid_user_details",
        "user_not_eligible",
        "international_transaction_not_allowed",
    }
)


def is_hard_decline(reason: str | None) -> bool:
    return reason in HARD_DECLINE_REASONS


# ---------------------------------------------------------------------------
# Payment methods Salvage models. The merchant fixture uses these four; the taxonomy above
# carries cardless_emi and emandate because Razorpay publishes them and the normaliser must not
# choke on them.
# ---------------------------------------------------------------------------


class Method(StrEnum):
    UPI = "upi"
    CARD = "card"
    NETBANKING = "netbanking"
    WALLET = "wallet"


# ---------------------------------------------------------------------------
# Root cause classes. docs/01_PRD.md section 7 and Architecture section 6.
# ---------------------------------------------------------------------------


class RootCause(StrEnum):
    ISSUER_OUTAGE = "issuer_outage"
    AUTH_FAILURE_BIN = "auth_failure_bin"
    GATEWAY_DEGRADATION = "gateway_degradation"
    MERCHANT_CONFIG = "merchant_config"
    CUSTOMER_SIDE = "customer_side"
    UNKNOWN = "unknown"
