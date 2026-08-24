"""Detector thresholds.

Architecture section 5 gives the starting values. Section 5 also says: "The threshold set above is
tuned once on S0 seed 0 and then frozen; seeds 1 to 4 are the held-out calibration."

FROZEN is that frozen set. It is a module-level constant rather than configuration on purpose: a
threshold that can be changed from a YAML file or the environment is a threshold that can be
changed after seeing the held-out seeds, and then the calibration means nothing. Changing these
values means editing this file, and the calibration table in docs/BUILD_LOG.md must be regenerated
and re-recorded when that happens.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Thresholds:
    # -- window ------------------------------------------------------------
    # Architecture section 5: "Window: 15 simulated minutes, evaluated every minute."
    window_seconds: int = 15 * 60
    step_seconds: int = 60

    # -- the four conditions ----------------------------------------------
    # 1. n >= 20 attempts in the window.
    min_attempts: int = 20
    # 2. observed rate minus baseline at least 0.15 absolute.
    min_absolute_excess: float = 0.15
    # 3. one-sided binomial p-value below 0.001, Bonferroni across the number of live keys,
    #    floored at 0.0001 so the correction cannot make the test unusable when many keys are live.
    alpha: float = 0.001
    alpha_floor: float = 0.0001
    # 4. conditions 1 to 3 hold in two consecutive windows.
    consecutive_windows: int = 2

    # -- baseline ----------------------------------------------------------
    # Trailing seven days at the same hour band, four bands per day.
    baseline_days: int = 7
    hour_bands_per_day: int = 4
    # Fall back to the key's overall trailing rate when the band has fewer than this many
    # attempts, then to the method-level rate.
    min_band_attempts: int = 200
    min_key_attempts: int = 200
    # A baseline of exactly zero makes the binomial test degenerate: a single failure then has a
    # p-value of zero and every key with a clean week fires on its first bad minute. The floor is
    # the smallest failure rate the detector is willing to believe in.
    min_baseline_rate: float = 0.005

    # -- attribution -------------------------------------------------------
    # Architecture section 5: attribute to the key that explains at least 80 percent of the excess
    # failures, so one fault produces one incident.
    attribution_share: float = 0.80

    # -- close -------------------------------------------------------------
    # "the key's rate is back within 0.05 of baseline for four consecutive windows and every
    # recovery case is terminal".
    close_within_of_baseline: float = 0.05
    close_consecutive_windows: int = 4

    def hour_band(self, hour: int) -> int:
        return hour // (24 // self.hour_bands_per_day)


# The frozen set. Tuned on S0 seed 0 only; seeds 1 to 4 are held out.
# Deviations from the values written in Architecture section 5, with reasons, are in
# docs/BUILD_LOG.md under M1 step 6.
FROZEN = Thresholds()
