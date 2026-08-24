"""Quiet-hour boundary and clock skew against the policy engine.

Architecture section 15's last row. The quiet-hour rule is the one bound whose correctness depends
on arithmetic rather than on a comparison, so it gets boundary tests on both edges and a check
that a clock an hour out cannot make a send land inside the window.
"""

from __future__ import annotations

import pytest

from salvage.decide.menu import ActionType
from salvage.decide.policy import (
    QUIET_HOURS_END,
    QUIET_HOURS_START,
    ActionContext,
    Decision,
    evaluate,
    next_quiet_hours_end,
)
from salvage.sim.clock import IstCalendar
from salvage.taxonomy import RootCause

CAL = IstCalendar()
# IST midnight, so hour arithmetic below is exact.
MIDNIGHT_IST = 1785522600


def _context(now: int) -> ActionContext:
    return ActionContext(
        action_type=ActionType.SEND_RECOVERY_LINK,
        cause=RootCause.ISSUER_OUTAGE.value,
        confidence=0.9,
        incident_id="inc_1",
        now=now,
        consent=True,
        order_paid=False,
        order_created_at=now - 3600,
        order_amount=200000,
        segment_degraded=False,
    )


@pytest.mark.parametrize(
    ("hour", "minute", "should_send"),
    [
        (20, 59, True),  # one minute before quiet hours
        (21, 0, False),  # the first minute of quiet hours
        (21, 1, False),
        (8, 59, False),  # the last minute of quiet hours
        (9, 0, True),  # the first minute after
        (9, 1, True),
        (0, 0, False),  # midnight is inside
        (23, 59, False),
    ],
)
def test_the_quiet_hour_boundary_is_exact(hour, minute, should_send, injection_log):
    now = MIDNIGHT_IST + hour * 3600 + minute * 60
    assert CAL.hour_of_day(now) == hour
    verdict = evaluate(_context(now), CAL)
    sent_now = verdict.decision == Decision.ALLOW
    assert sent_now is should_send, f"{hour:02d}:{minute:02d}"
    if not should_send:
        assert verdict.decision == Decision.QUEUE
        assert CAL.hour_of_day(verdict.scheduled_for) == QUIET_HOURS_END
        injection_log.record(
            category="timing",
            attack=f"send due at {hour:02d}:{minute:02d} IST",
            refused=True,
            ledgered=True,
            detail="queued for 09:00 IST, not dropped and not sent",
        )


def test_a_queued_send_never_lands_back_inside_quiet_hours(injection_log):
    """Queueing to a time that is itself inside quiet hours would be worse than refusing."""
    for offset in range(0, 24 * 3600, 900):
        now = MIDNIGHT_IST + offset
        target = next_quiet_hours_end(now, CAL)
        assert target > now
        assert not CAL.is_quiet_hours(target, QUIET_HOURS_START, QUIET_HOURS_END)
    injection_log.record(
        category="timing",
        attack="queue target landing inside quiet hours",
        refused=True,
        ledgered=False,
        detail="96 quarter-hour probes across a day, every target at 09:00 IST",
    )


@pytest.mark.parametrize("skew_hours", [-2, -1, 1, 2])
def test_clock_skew_cannot_open_a_hole_in_quiet_hours(skew_hours, injection_log):
    """A clock that is wrong shifts which sends are held, and never lets one through untested.

    The rule is evaluated against the clock the process has. What must not happen is a send that
    the engine believes is outside quiet hours while its own arithmetic says otherwise.
    """
    for hour in range(24):
        now = MIDNIGHT_IST + hour * 3600 + skew_hours * 3600
        verdict = evaluate(_context(now), CAL)
        in_quiet = CAL.is_quiet_hours(now, QUIET_HOURS_START, QUIET_HOURS_END)
        assert (verdict.decision == Decision.ALLOW) is not in_quiet
    injection_log.record(
        category="timing",
        attack=f"clock skewed by {skew_hours:+d} hours",
        refused=True,
        ledgered=False,
        detail="the decision always matches the engine's own quiet-hour arithmetic",
    )


def test_a_ttl_that_has_passed_refuses_regardless_of_the_hour(injection_log):
    context = ActionContext(
        action_type=ActionType.SEND_RECOVERY_LINK,
        cause=RootCause.ISSUER_OUTAGE.value,
        confidence=0.9,
        incident_id="inc_1",
        now=MIDNIGHT_IST + 12 * 3600,
        consent=True,
        order_paid=False,
        order_created_at=MIDNIGHT_IST - 100 * 3600,
        order_amount=200000,
    )
    verdict = evaluate(context, CAL)
    assert verdict.decision == Decision.REFUSE
    assert verdict.refusing_rule == "case.within_ttl"
    injection_log.record(
        category="timing",
        attack="send attempted 100 hours after the order",
        refused=True,
        ledgered=True,
        detail="72 hour TTL refuses it",
    )


def test_every_injection_attempt_was_refused(injection_log):
    """The exit criterion, asserted rather than eyeballed.

    Runs last in this module. pytest executes files in alphabetical order and this one sorts last,
    so by the time it runs every other injection has been recorded.
    """
    summary = injection_log.summary()
    assert summary["attempts"] > 0
    assert summary["unrefused"] == [], summary["unrefused"]
    assert summary["refused"] == summary["attempts"]
    assert summary["fault_tolerance_handled"] == summary["fault_tolerance_cases"]
