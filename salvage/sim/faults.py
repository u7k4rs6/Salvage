"""Fault scenarios.

Architecture section 9: "a scenario is a list of {segment_selector, start, duration,
failure_rate, error_profile}". The scenarios themselves are data in sim/params.yaml; this module
turns them into a schedule against the sim clock and decides, per attempt, whether a fault is
responsible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from salvage.sim.params import Fault, Params, Scenario


@dataclass(frozen=True)
class ScheduledFault:
    """A fault with absolute sim-clock bounds."""

    fault: Fault
    start_ts: int
    end_ts: int

    def active_at(self, ts: int) -> bool:
        return self.start_ts <= ts < self.end_ts

    def applies_to(self, ts: int, attempt: dict[str, Any]) -> bool:
        return self.active_at(ts) and self.fault.matches(attempt)


def schedule(
    scenario: Scenario, params: Params, *, eval_day_start: int, seed: int
) -> list[ScheduledFault]:
    """Place a scenario's faults on the sim clock.

    start_minute is minutes into the evaluation day in IST, and eval_day_start is already the IST
    midnight of that day, so the arithmetic is a plain addition.

    The seed-dependent jitter keeps five seeds from breaking at the same minute. It is derived
    from the seed alone, not from a random stream, so it does not consume draws that the world
    streams rely on and cannot shift customers or arrivals.
    """
    jitter_span = params.fault_start_jitter_minutes
    scheduled: list[ScheduledFault] = []
    for index, fault in enumerate(scenario.faults):
        jitter = ((seed * 37 + index * 13) % (jitter_span + 1)) if jitter_span > 0 else 0
        start = eval_day_start + (fault.start_minute + jitter) * 60
        scheduled.append(
            ScheduledFault(
                fault=fault,
                start_ts=start,
                end_ts=start + fault.duration_minutes * 60,
            )
        )
    return scheduled


def active_fault(
    scheduled: list[ScheduledFault], ts: int, attempt: dict[str, Any]
) -> ScheduledFault | None:
    """The first fault matching this attempt at this time, or None.

    First rather than a combination: no scenario in params.yaml has two faults whose selectors
    overlap, and combining failure rates would need a composition rule that is not in the
    documents. If a future scenario needs overlapping faults, this is the one place to change.
    """
    for candidate in scheduled:
        if candidate.applies_to(ts, attempt):
            return candidate
    return None


def config_changed_recently(scheduled: list[ScheduledFault], ts: int) -> bool:
    """Whether the evidence packet's merchant_config_changed_recently flag should be true.

    True while a fault that sets the flag is active, and for a lookback window afterwards, because
    a merchant does not un-change a setting the moment the errors stop.
    """
    lookback = 6 * 3600
    return any(
        candidate.fault.sets_config_changed_flag
        and candidate.start_ts - lookback <= ts < candidate.end_ts + lookback
        for candidate in scheduled
    )
