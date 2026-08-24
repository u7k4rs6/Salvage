"""Customer response model.

Architecture section 9. M1 implements the organic part only:

  "every failed order gets an organic retry probability within 24 hours (p_organic, by order
  value band)."

Interventions (nudges, steers, the multipliers and the 12 hour decay) arrive in M2. Their
parameters are already in sim/params.yaml so the instrument is legible as a whole, and
M2_MULTIPLIERS_ARE_UNUSED_IN_M1 below records that nothing here reads them yet.

Everything in this module draws from the "response" substream, in order-creation order. That
order is set by the world, not by any policy, so agent and baselines get the same organic
outcomes for the same customers (see salvage/sim/rng.py).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from salvage import taxonomy
from salvage.sim.params import Params

M2_MULTIPLIERS_ARE_UNUSED_IN_M1 = True


@dataclass(frozen=True)
class OrganicOutcome:
    """The counterfactual: what this customer would do with no intervention at all."""

    p_organic: float
    will_retry: bool
    retry_at: int | None  # sim seconds, None when will_retry is False


def p_organic_for_amount(params: Params, amount_paise: int) -> float:
    """Value-band lookup. The last band has max_paise null and catches everything above."""
    for band in params.response["p_organic_by_value_band"]:
        limit = band["max_paise"]
        if limit is None or amount_paise < int(limit):
            return float(band["p"])
    raise AssertionError("the last value band must have max_paise: null")  # pragma: no cover


class ResponseModel:
    """Draws organic outcomes. One instance per run."""

    def __init__(self, params: Params, rng: np.random.Generator) -> None:
        self._params = params
        self._rng = rng
        response = params.response
        self._mu = float(response["organic_retry_delay_lognormal_mu"])
        self._sigma = float(response["organic_retry_delay_lognormal_sigma"])
        self._max_minutes = int(response["organic_retry_max_minutes"])
        self._hard_decline_multiplier = float(response["p_organic_hard_decline_multiplier"])

    def draw(
        self, *, amount_paise: int, failed_at: int, error_reason: str | None
    ) -> OrganicOutcome:
        """Draw the counterfactual for one failed order.

        Exactly three values are drawn every time, whatever the outcome, so the stream stays
        aligned: a change to the branching cannot shift later orders' draws.
        """
        retry_draw = float(self._rng.random())
        delay_draw = float(self._rng.normal(self._mu, self._sigma))
        _reserved = float(self._rng.random())  # noqa: F841  keeps the draw count fixed at three

        p = p_organic_for_amount(self._params, amount_paise)
        if taxonomy.is_hard_decline(error_reason):
            # The instrument itself is refused, so trying the same one again mostly fails.
            p *= self._hard_decline_multiplier

        if retry_draw >= p:
            return OrganicOutcome(p_organic=p, will_retry=False, retry_at=None)

        minutes = min(float(np.exp(delay_draw)), float(self._max_minutes))
        return OrganicOutcome(
            p_organic=p,
            will_retry=True,
            retry_at=failed_at + int(round(minutes * 60)),
        )
