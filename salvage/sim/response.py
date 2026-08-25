"""Customer response model.

Architecture section 9. Two halves:

  Organic. "every failed order gets an organic retry probability within 24 hours (p_organic, by
  order value band)." An organic retry is a real payment attempt on the same order with the same
  instrument, so it fails again if the rail is still broken. That is the whole reason cause-aware
  timing is worth anything, and it is why a run has more attempts than orders.

  Interventions. The multipliers in ResponseModel.intervention_multiplier, all from sim/params.yaml.

Every draw is keyed by order index, not taken in sequence from a shared stream. An order that a
recovery link pays never makes the organic retries it would have made, so a sequential stream
would shift every later order's draws the moment a policy acted. See salvage/sim/rng.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from salvage import taxonomy
from salvage.sim.params import Params
from salvage.sim.rng import order_stream

ORGANIC_STREAM = "response"
INTERVENTION_STREAM = "intervention"
# The repair draw has its own stream so that turning the escalation fix on cannot shift a single
# draw any other part of the model takes. That is what makes the T = never row reproduce the
# pre-M5 numbers exactly rather than approximately.
REPAIR_STREAM = "repair"


@dataclass(frozen=True)
class PlannedRetry:
    """One organic retry the customer would make with no intervention at all.

    failure_draw and profile_draw are fixed now rather than at retry time, so whether this retry
    succeeds depends only on the rail's state when it lands, never on how many draws some other
    order consumed first.
    """

    at: int
    failure_draw: float
    profile_draw: float
    retry_index: int


@dataclass(frozen=True)
class OrganicPlan:
    p_organic: float
    retries: tuple[PlannedRetry, ...]

    @property
    def will_retry(self) -> bool:
        return bool(self.retries)

    @property
    def first_retry_at(self) -> int | None:
        return self.retries[0].at if self.retries else None


@dataclass(frozen=True)
class RepairPlan:
    """Whether an at-risk customer comes back after the rail is repaired, and when."""

    probability: float
    returns: bool
    at: int | None


def p_organic_for_amount(params: Params, amount_paise: int) -> float:
    """Value-band lookup. The last band has max_paise null and catches everything above."""
    for band in params.response["p_organic_by_value_band"]:
        limit = band["max_paise"]
        if limit is None or amount_paise < int(limit):
            return float(band["p"])
    raise AssertionError("the last value band must have max_paise: null")  # pragma: no cover


class ResponseModel:
    """Draws counterfactual customer behaviour. One instance per run."""

    def __init__(self, params: Params, seed: int) -> None:
        self._params = params
        self._seed = int(seed)
        response = params.response
        self._mu = float(response["organic_retry_delay_lognormal_mu"])
        self._sigma = float(response["organic_retry_delay_lognormal_sigma"])
        self._max_minutes = int(response["organic_retry_max_minutes"])
        self._hard_decline_multiplier = float(response["p_organic_hard_decline_multiplier"])
        self._max_retries = int(response["max_organic_retries"])
        self._decay = float(response["repeat_retry_decay"])

        multipliers = response["m2_multipliers"]
        self._m_still_failing = float(multipliers["nudge_while_method_still_failing"])
        self._m_recovered = float(multipliers["nudge_after_recovery_or_with_alternate"])
        self._m_cap = float(multipliers["nudge_multiplier_cap"])
        self._m_steer = float(multipliers["live_checkout_steer_during_failing_session"])
        self._m_second_nudge = float(multipliers["second_nudge_multiplier"])
        self._decay_hours = float(multipliers["decay_time_constant_hours"])
        self._opt_out_base = float(multipliers["opt_out_probability_base"])
        self._opt_out_still_failing = float(multipliers["opt_out_probability_still_failing"])

    @property
    def organic_horizon_seconds(self) -> int:
        """How long after a failure the model still lets a customer come back at all.

        organic_retry_max_minutes, reused rather than re-invented. A repair that lands after this
        is a repair nobody was still waiting for.
        """
        return self._max_minutes * 60

    # -- organic -----------------------------------------------------------

    def base_probability(self, *, amount_paise: int, error_reason: str | None) -> float:
        p = p_organic_for_amount(self._params, amount_paise)
        if taxonomy.is_hard_decline(error_reason):
            # The instrument itself is refused, so trying the same one again mostly fails.
            p *= self._hard_decline_multiplier
        return p

    def organic_plan(
        self,
        *,
        order_index: int,
        amount_paise: int,
        first_failed_at: int,
        error_reason: str | None,
    ) -> OrganicPlan:
        """The whole chain of organic retries this order would see with no intervention.

        Drawn once, when the order's first attempt fails, from that order's own stream. The chain
        stops at the first draw that says the customer does not come back, at max_organic_retries,
        or when the next retry would fall outside organic_retry_max_minutes of the first failure.
        """
        base = self.base_probability(amount_paise=amount_paise, error_reason=error_reason)
        rng = order_stream(self._seed, ORGANIC_STREAM, order_index)

        retries: list[PlannedRetry] = []
        deadline = first_failed_at + self._max_minutes * 60
        at = first_failed_at
        for retry_index in range(self._max_retries):
            # Four draws per potential retry, always taken, so the chain length cannot shift the
            # meaning of a later draw.
            comes_back = float(rng.random())
            delay = float(rng.normal(self._mu, self._sigma))
            failure_draw = float(rng.random())
            profile_draw = float(rng.random())

            probability = base * (self._decay**retry_index)
            if comes_back >= probability:
                break
            minutes = min(float(np.exp(delay)), float(self._max_minutes))
            at = at + int(round(minutes * 60))
            if at > deadline:
                break
            retries.append(
                PlannedRetry(
                    at=at,
                    failure_draw=failure_draw,
                    profile_draw=profile_draw,
                    retry_index=retry_index,
                )
            )
        return OrganicPlan(p_organic=base, retries=tuple(retries))

    # -- interventions -----------------------------------------------------

    def intervention_multiplier(
        self,
        *,
        method_still_failing: bool,
        alternate_offered: bool,
        nudge_number: int,
        hours_since_failure: float,
    ) -> float:
        """Multiplier applied to p_organic when a nudge reaches the customer.

        Architecture section 9, every number from sim/params.yaml:
          a nudge while the customer's method is still failing multiplies by 0.3
          a nudge after recovery or with a working alternate offered multiplies by 2.2
          a second nudge halves the multiplier
          everything decays with a 12 hour time constant
        The cap is applied to the resulting probability, not to the multiplier, because
        "capped at 0.8" in the document is a statement about how likely a customer can be made to
        come back, which is a probability.
        """
        if method_still_failing and not alternate_offered:
            multiplier = self._m_still_failing
        else:
            multiplier = self._m_recovered
        if nudge_number >= 2:
            multiplier *= self._m_second_nudge
        return multiplier * self._time_decay(hours_since_failure)

    def steer_multiplier(self, *, hours_since_failure: float = 0.0) -> float:
        """A live checkout steer during the failing session gives a fixed 0.55 (Architecture 9).

        Fixed means fixed: it is a probability, not a multiplier, so it is returned as is and the
        caller uses it directly rather than multiplying p_organic by it.
        """
        del hours_since_failure
        return self._m_steer

    def apply_multiplier(self, base_probability: float, multiplier: float) -> float:
        return min(self._m_cap, base_probability * multiplier)

    def opt_out_probability(self, *, method_still_failing: bool) -> float:
        """A nudge into a still-failing rail raises the chance the customer opts out."""
        return self._opt_out_still_failing if method_still_failing else self._opt_out_base

    def _time_decay(self, hours_since_failure: float) -> float:
        if self._decay_hours <= 0:
            return 1.0
        return math.exp(-max(0.0, hours_since_failure) / self._decay_hours)

    # -- escalation to fix -------------------------------------------------

    def repair_plan(
        self,
        *,
        order_index: int,
        amount_paise: int,
        error_reason: str | None,
        first_failed_at: int,
        fixed_at: int,
    ) -> RepairPlan:
        """What one at-risk customer does when the rail they failed on is repaired.

        One further chance to come back, and no more than that. The probability is the order's
        own organic probability decayed by the same time constant the intervention multipliers
        use, so a fix that lands eight hours later is worth less than one that lands in twenty
        minutes, and a fix never makes a customer more likely to return than they were at the
        moment their payment failed. No new tunable number: every input is a parameter that
        already existed before the fix mechanism did.
        """
        base = self.base_probability(amount_paise=amount_paise, error_reason=error_reason)
        hours = max(0.0, (fixed_at - first_failed_at) / 3600.0)
        probability = base * self._time_decay(hours)
        rng = order_stream(self._seed, REPAIR_STREAM, order_index)
        comes_back = float(rng.random())
        delay = float(rng.normal(self._mu, self._sigma))
        if comes_back >= probability:
            return RepairPlan(probability=probability, returns=False, at=None)
        minutes = min(float(np.exp(delay)), float(self._max_minutes))
        return RepairPlan(
            probability=probability,
            returns=True,
            at=fixed_at + int(round(minutes * 60)),
        )

    def intervention_draw(
        self, *, order_index: int, nudge_number: int
    ) -> tuple[float, float, float]:
        """(pays draw, opts-out draw, pay-delay draw) for one nudge to one order.

        Keyed by order and nudge number, so B1 sending a first nudge and the agent sending a first
        nudge to the same customer resolve against the same random value. That is what makes the
        comparison in docs/RESULTS.md a comparison of decisions rather than of luck.

        Three draws, always taken in this order, so a policy that ignores one of them cannot shift
        the others.
        """
        rng = order_stream(self._seed, f"{INTERVENTION_STREAM}:{nudge_number}", order_index)
        return float(rng.random()), float(rng.random()), float(rng.random())
