"""Traffic generator.

Architecture section 9: "Poisson arrivals with a diurnal curve peaking 19:00 to 23:00 ... Method
mix: UPI 60 percent (handles distributed across five bank handles), cards 25 percent (BIN ranges
mapped to issuers and networks), netbanking 10 percent, wallets 5 percent. Organic failure rates
per method with a source, step and reason distribution taken from Razorpay's public error
taxonomy."

Output is a stream of Razorpay payment entities, the same shape the webhook carries, so both go
through salvage/ingest/normalize.py and the detector cannot tell them apart.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import numpy as np

from salvage.sim.clock import DAY_SECONDS, IstCalendar
from salvage.sim.faults import ScheduledFault, active_fault
from salvage.sim.merchant import SimCustomer, Sku
from salvage.sim.params import ErrorProfileEntry, Params
from salvage.sim.rng import Streams, pick, weighted_choice_table
from salvage.taxonomy import error_code_for_reason

# Razorpay's own error_description strings, transcribed from the error pages so the sample
# descriptions in an evidence packet look like the real thing. Keyed by reason; anything without
# an entry gets a generic string built from the reason, which is also what Razorpay does for the
# reasons it does not document a sentence for.
DESCRIPTIONS: dict[str, str] = {
    "insufficient_funds": "Your payment failed as there were insufficient funds in your account.",
    "payment_timed_out": "Payment was not completed on time.",
    "payment_cancelled": "Payment processing cancelled by user",
    "bank_technical_error": "Payment failed due to a technical error at bank. Try another method.",
    "bank_not_available": "Your payment failed as the bank was unavailable. Try another method.",
    "vpa_resolution_failed": "Your payment could not be processed using the UPI ID entered.",
    "invalid_vpa": "Your payment failed as the UPI ID entered is not valid.",
    "gateway_technical_error": "Your payment failed due to a technical error. Please try again.",
    "psp_not_available": "Your payment failed as the UPI app was not available.",
    "transaction_limit_exceeded": "You have exceeded the transaction limit on your card.",
    "authentication_failed": "Your payment failed as the authentication could not be completed.",
    "incorrect_otp": "Your payment failed as an incorrect OTP was entered.",
    "incorrect_cvv": "Your payment failed as an incorrect CVV was entered.",
    "card_declined": "Your payment was declined by your bank. Try another card or method.",
    "card_expired": "Your payment failed as the card has expired.",
    "card_not_enrolled": "Your payment failed as the card is not enrolled for authentication.",
    "otp_attempts_exceeded": "Your payment failed as the OTP attempts limit was exceeded.",
    "payment_risk_check_failed": "Your payment was declined by your bank as a risk check failed.",
    "payment_declined": "Your payment was declined. Please try again.",
    "payment_declined_due_to_high_traffic": "Your payment failed due to high traffic. Try again.",
    "request_timed_out": "Your payment failed as the request timed out.",
    "invalid_response_from_gateway": "Your payment failed due to an invalid gateway response.",
    "issuer_technical_error": "Your payment failed due to a technical error at the issuer.",
    "user_not_registered_for_netbanking": "You are not registered for netbanking with this bank.",
    "payment_method_not_enabled": "This payment method is not enabled for this merchant.",
    "bank_not_enabled": "The selected bank is not enabled for this merchant.",
    "input_validation_failed": "Payment failed due to an invalid value in the payment request.",
    "invalid_amount": "The amount in the payment request is not supported.",
}


def description_for(reason: str) -> str:
    return DESCRIPTIONS.get(reason, f"Your payment failed. Reason: {reason}.")


@dataclass(frozen=True)
class GeneratedAttempt:
    """One simulated payment attempt, plus the ground truth that goes with it."""

    entity: dict[str, Any]  # the Razorpay payment entity
    customer_id: str
    order_id: str
    order_index: int
    order_amount: int
    created_at: int
    failed: bool
    fault_caused: bool
    truth_cause: str  # a RootCause value, or "organic", or "none" for a success
    # 0 for the first attempt on an order, 1 for the first organic retry, and so on.
    retry_index: int = 0
    error_reason: str | None = None

    @property
    def is_retry(self) -> bool:
        return self.retry_index > 0


class _ProfileSampler:
    """Weighted sampler over an error profile."""

    def __init__(self, profile: tuple[ErrorProfileEntry, ...]) -> None:
        self._entries = profile
        self._table = weighted_choice_table([entry.weight for entry in profile])

    def pick(self, draw: float) -> ErrorProfileEntry:
        return self._entries[pick(self._table, draw)]


def arrivals_per_minute(
    params: Params,
    day_start: int,
    rng: np.random.Generator,
    *,
    scenario_id: str | None = None,
) -> np.ndarray:
    """Poisson counts for each of a day's 1440 minutes.

    The diurnal weights are relative, so they are normalised here: the expected daily total is
    exactly attempts_per_day whatever the weights sum to.

    Volume comes from params.attempts_per_day(scenario_id), never from the raw dict, because it is
    a scenario parameter that M3's volume sweep overrides.
    """
    calendar = IstCalendar(params.ist_offset)
    weights = params.traffic["diurnal_weights"]
    per_day = float(params.attempts_per_day(scenario_id))
    hourly = np.array([float(weights[h]) for h in range(24)])
    hourly = hourly / hourly.sum()
    minute_rate = np.empty(1440, dtype=float)
    for minute in range(1440):
        hour = calendar.hour_of_day(day_start + minute * 60)
        minute_rate[minute] = per_day * hourly[hour] / 60.0
    return rng.poisson(minute_rate)


class TrafficGenerator:
    """Generates attempts day by day. One instance per run."""

    def __init__(
        self,
        params: Params,
        streams: Streams,
        customers: list[SimCustomer],
        catalogue: list[Sku],
        scenario_id: str | None = None,
    ) -> None:
        self._params = params
        self._scenario_id = scenario_id
        self._streams = streams
        self._customers = customers
        self._catalogue = catalogue
        self._calendar = IstCalendar(params.ist_offset)
        self._organic_rate = params.organic["failure_rate_by_method"]
        self._organic_samplers = {
            method: _ProfileSampler(params.organic_profile(method))
            for method in params.organic["error_profiles"]
        }
        self._fault_samplers: dict[int, _ProfileSampler] = {}
        self._counter = 0
        self._order_counter = 0

    def _fault_sampler(self, fault: ScheduledFault) -> _ProfileSampler:
        """One sampler per fault, built once. Building it per attempt showed up as the hottest
        line in the generator when the run was first profiled."""
        key = id(fault.fault)
        sampler = self._fault_samplers.get(key)
        if sampler is None:
            sampler = _ProfileSampler(fault.fault.error_profile)
            self._fault_samplers[key] = sampler
        return sampler

    # -- entity construction ---------------------------------------------

    def _instrument_fields(self, customer: SimCustomer) -> dict[str, Any]:
        """The Razorpay payment entity fields that describe the instrument.

        Every attempt uses the customer's preferred instrument. The alternate exists so the M2
        policy engine can ask whether a customer has another rail; it is not used for traffic,
        which is why the observed method mix equals the configured method mix exactly.
        """
        instrument = customer.preferred
        fields: dict[str, Any] = {"method": instrument.method}
        if instrument.method == "upi":
            # Razorpay's UPI payments carry the VPA and the 4-character bank code.
            fields["vpa"] = f"{customer.customer_id}@{instrument.upi_handle}"
            fields["bank"] = instrument.upi_bank
        elif instrument.method == "card":
            fields["card"] = {
                "entity": "card",
                "iin": instrument.card_bin,
                "last4": instrument.card_bin[-4:] if instrument.card_bin else None,
                "network": instrument.card_network,
                "issuer": instrument.card_issuer,
                "type": "debit",
                "international": False,
            }
        elif instrument.method == "netbanking":
            fields["bank"] = instrument.nb_bank
        elif instrument.method == "wallet":
            fields["wallet"] = instrument.wallet
        return fields

    def _entity(
        self,
        *,
        payment_id: str,
        order_id: str,
        amount: int,
        created_at: int,
        instrument: dict[str, Any],
        failure: ErrorProfileEntry | None,
    ) -> dict[str, Any]:
        """A Razorpay payment entity, field for field.

        Shape from razorpay.com/docs/api/payments/entity/ and
        razorpay.com/docs/webhooks/payloads/payments/. Fields Salvage does not use are still
        present, because the normaliser has to survive them and the detector must not be able to
        tell a simulated entity from a real one.
        """
        entity: dict[str, Any] = {
            "id": payment_id,
            "entity": "payment",
            "amount": amount,
            "currency": "INR",
            "status": "failed" if failure else "captured",
            "order_id": order_id,
            "invoice_id": None,
            "international": False,
            "amount_refunded": 0,
            "refund_status": None,
            "captured": failure is None,
            "description": "Order from Kettle and Cloth",
            "card_id": None,
            "fee": None,
            "tax": None,
            "created_at": created_at,
            "notes": {},
            "acquirer_data": {},
        }
        entity.update(instrument)
        if failure is not None:
            entity["error_code"] = error_code_for_reason(failure.reason)
            entity["error_description"] = description_for(failure.reason)
            entity["error_source"] = failure.source
            entity["error_step"] = failure.step
            entity["error_reason"] = failure.reason
        else:
            entity["error_code"] = None
            entity["error_description"] = None
            entity["error_source"] = None
            entity["error_step"] = None
            entity["error_reason"] = None
        return entity

    # -- generation -------------------------------------------------------

    def generate_day(
        self, day_start: int, scheduled: list[ScheduledFault]
    ) -> Iterator[GeneratedAttempt]:
        """One simulated day of attempts, in time order."""
        arrivals = arrivals_per_minute(
            self._params, day_start, self._streams.arrivals, scenario_id=self._scenario_id
        )
        total = int(arrivals.sum())
        if total == 0:
            return

        rng = self._streams.attempts
        customer_draws = rng.integers(0, len(self._customers), size=total)
        sku_draws = rng.integers(0, len(self._catalogue), size=total)
        amount_jitter = rng.normal(0.0, 0.18, size=total)
        failure_draws = rng.random(total)
        profile_draws = rng.random(total)
        second_draws = rng.integers(0, 60, size=total)

        index = 0
        for minute, count in enumerate(arrivals):
            minute_start = day_start + minute * 60
            for _ in range(int(count)):
                yield self._one(
                    ts=minute_start + int(second_draws[index]),
                    customer=self._customers[int(customer_draws[index])],
                    sku=self._catalogue[int(sku_draws[index])],
                    amount_jitter=float(amount_jitter[index]),
                    failure_draw=float(failure_draws[index]),
                    profile_draw=float(profile_draws[index]),
                    scheduled=scheduled,
                )
                index += 1

    def _resolve_outcome(
        self,
        *,
        ts: int,
        customer: SimCustomer,
        failure_draw: float,
        profile_draw: float,
        scheduled: list[ScheduledFault],
    ) -> tuple[bool, bool, str, ErrorProfileEntry | None]:
        """Did this attempt fail, was the fault to blame, and with which error.

        Shared by first attempts and by organic retries, so a retry made while the rail is still
        broken fails for the same reason the first attempt did. That is the behaviour that makes
        nudging into a dead rail expensive.
        """
        instrument = customer.preferred
        selector_view = {
            "method": instrument.method,
            "upi_handle": instrument.upi_handle,
            "card_bin": instrument.card_bin,
            "card_issuer": instrument.card_issuer,
            "card_network": instrument.card_network,
            "nb_bank": instrument.nb_bank,
            "wallet": instrument.wallet,
        }
        fault = active_fault(scheduled, ts, selector_view)
        organic_rate = float(self._organic_rate[instrument.method])

        if fault is not None:
            if fault.fault.additive:
                # S5's shape: the fault adds failures on top of the organic rate.
                rate = min(1.0, organic_rate + fault.fault.failure_rate)
                fault_share = (rate - organic_rate) / rate if rate > 0 else 0.0
            else:
                # Everything else replaces the organic rate for matching attempts.
                rate = fault.fault.failure_rate
                fault_share = 1.0 if rate > 0 else 0.0
        else:
            rate, fault_share = organic_rate, 0.0

        if failure_draw >= rate:
            return False, False, "none", None

        # A failure inside a fault window is attributed to the fault with probability
        # fault_share, which is 1.0 for a replacing fault and the excess share for an additive
        # one. profile_draw picks the reason within whichever profile applies.
        fault_caused = fault is not None and (failure_draw / max(rate, 1e-12)) < fault_share
        if fault_caused:
            assert fault is not None
            sampler = self._fault_sampler(fault)
            truth_cause = fault.fault.truth_cause
        else:
            sampler = self._organic_samplers[instrument.method]
            truth_cause = "organic"
        return True, fault_caused, truth_cause, sampler.pick(profile_draw)

    def _one(
        self,
        *,
        ts: int,
        customer: SimCustomer,
        sku: Sku,
        amount_jitter: float,
        failure_draw: float,
        profile_draw: float,
        scheduled: list[ScheduledFault],
    ) -> GeneratedAttempt:
        self._counter += 1
        self._order_counter += 1
        order_index = self._order_counter
        payment_id = f"pay_sim{self._counter:012d}"
        order_id = f"order_sim{order_index:012d}"

        # Order value: the SKU price pulled toward the customer's typical spend, so a customer's
        # basket has a persistent level. Clamped to the catalogue bounds.
        merchant = self._params.merchant
        blended = 0.6 * sku.amount + 0.4 * customer.typical_amount
        amount = int(round(blended * float(np.exp(amount_jitter))))
        amount = max(int(merchant["sku_min_paise"]), min(int(merchant["sku_max_paise"]), amount))

        failed, fault_caused, truth_cause, failure = self._resolve_outcome(
            ts=ts,
            customer=customer,
            failure_draw=failure_draw,
            profile_draw=profile_draw,
            scheduled=scheduled,
        )
        entity = self._entity(
            payment_id=payment_id,
            order_id=order_id,
            amount=amount,
            created_at=ts,
            instrument=self._instrument_fields(customer),
            failure=failure,
        )
        return GeneratedAttempt(
            entity=entity,
            customer_id=customer.customer_id,
            order_id=order_id,
            order_index=order_index,
            order_amount=amount,
            created_at=ts,
            failed=failed,
            fault_caused=fault_caused,
            truth_cause=truth_cause,
            retry_index=0,
            error_reason=failure.reason if failure else None,
        )

    def retry(
        self,
        *,
        ts: int,
        customer: SimCustomer,
        order_id: str,
        order_index: int,
        amount: int,
        retry_index: int,
        failure_draw: float,
        profile_draw: float,
        scheduled: list[ScheduledFault],
    ) -> GeneratedAttempt:
        """A later attempt on an existing order, same customer, same instrument.

        This is what makes attempts exceed orders. The customer is trying the rail they always
        use, so if that rail is still broken the retry fails for the same reason.
        """
        self._counter += 1
        payment_id = f"pay_sim{self._counter:012d}"
        failed, fault_caused, truth_cause, failure = self._resolve_outcome(
            ts=ts,
            customer=customer,
            failure_draw=failure_draw,
            profile_draw=profile_draw,
            scheduled=scheduled,
        )
        entity = self._entity(
            payment_id=payment_id,
            order_id=order_id,
            amount=amount,
            created_at=ts,
            instrument=self._instrument_fields(customer),
            failure=failure,
        )
        return GeneratedAttempt(
            entity=entity,
            customer_id=customer.customer_id,
            order_id=order_id,
            order_index=order_index,
            order_amount=amount,
            created_at=ts,
            failed=failed,
            fault_caused=fault_caused,
            truth_cause=truth_cause,
            retry_index=retry_index,
            error_reason=failure.reason if failure else None,
        )


def day_starts(params: Params) -> list[int]:
    """IST midnights for the warm-up days and then the evaluation day."""
    total = params.warmup_days + params.eval_days
    return [params.epoch + day * DAY_SECONDS for day in range(total)]


def eval_day_start(params: Params) -> int:
    return params.epoch + params.warmup_days * DAY_SECONDS
