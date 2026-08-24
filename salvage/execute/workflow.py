"""Per-order recovery state machine.

docs/02_TECHNICAL_ARCHITECTURE.md section 8 draws it:

  [*] -> DETECTED
  DETECTED -> ELIGIBLE            consent, unpaid, no hard decline
  DETECTED -> CLOSED_NO_ACTION    no consent or below threshold
  ELIGIBLE -> DEFERRED            cause active or quiet hours
  DEFERRED -> ELIGIBLE            segment recovered and 09:00 reached
  ELIGIBLE -> LINK_CREATED        Payment Link created
  LINK_CREATED -> NUDGED          message sent
  NUDGED -> WAITING
  WAITING -> NUDGED               second nudge allowed
  WAITING -> RECOVERED            payment_link.paid
  WAITING -> PAID_ELSEWHERE       order.paid via another route, link cancelled
  WAITING -> OPTED_OUT            opt-out received
  WAITING -> ABANDONED            TTL 72h
  ELIGIBLE -> ESCALATED           gate refused on matrix
  DEFERRED -> ABANDONED           TTL 72h

The transition table below is that diagram, transcribed. `advance` refuses any transition not in
it, so the machine cannot reach a state by accident: a bug produces an exception at the transition
rather than a case in an impossible state three steps later.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CaseState(StrEnum):
    DETECTED = "DETECTED"
    ELIGIBLE = "ELIGIBLE"
    DEFERRED = "DEFERRED"
    LINK_CREATED = "LINK_CREATED"
    NUDGED = "NUDGED"
    WAITING = "WAITING"
    RECOVERED = "RECOVERED"
    PAID_ELSEWHERE = "PAID_ELSEWHERE"
    OPTED_OUT = "OPTED_OUT"
    ABANDONED = "ABANDONED"
    ESCALATED = "ESCALATED"
    CLOSED_NO_ACTION = "CLOSED_NO_ACTION"


# States from which nothing further happens. A terminal case is invisible to the policy engine's
# case check and to the scheduler.
TERMINAL_STATES = frozenset(
    {
        CaseState.RECOVERED,
        CaseState.PAID_ELSEWHERE,
        CaseState.OPTED_OUT,
        CaseState.ABANDONED,
        CaseState.CLOSED_NO_ACTION,
        CaseState.ESCALATED,
    }
)

# Outcomes recorded on a terminal case. docs/01_PRD.md section 7: paid via link, paid on organic
# retry, not recovered, opted out, escalated.
TERMINAL_OUTCOME: dict[CaseState, str] = {
    CaseState.RECOVERED: "RECOVERED",
    CaseState.PAID_ELSEWHERE: "PAID_ELSEWHERE",
    CaseState.OPTED_OUT: "OPTED_OUT",
    CaseState.ABANDONED: "ABANDONED",
    CaseState.CLOSED_NO_ACTION: "CLOSED_NO_ACTION",
    CaseState.ESCALATED: "ESCALATED",
}

TRANSITIONS: dict[CaseState, frozenset[CaseState]] = {
    CaseState.DETECTED: frozenset(
        {CaseState.ELIGIBLE, CaseState.CLOSED_NO_ACTION, CaseState.PAID_ELSEWHERE}
    ),
    CaseState.ELIGIBLE: frozenset(
        {
            CaseState.DEFERRED,
            CaseState.LINK_CREATED,
            CaseState.ESCALATED,
            CaseState.PAID_ELSEWHERE,
            CaseState.ABANDONED,
        }
    ),
    CaseState.DEFERRED: frozenset(
        {CaseState.ELIGIBLE, CaseState.ABANDONED, CaseState.PAID_ELSEWHERE}
    ),
    CaseState.LINK_CREATED: frozenset(
        {CaseState.NUDGED, CaseState.PAID_ELSEWHERE, CaseState.ABANDONED}
    ),
    CaseState.NUDGED: frozenset({CaseState.WAITING, CaseState.PAID_ELSEWHERE, CaseState.RECOVERED}),
    CaseState.WAITING: frozenset(
        {
            CaseState.NUDGED,
            CaseState.RECOVERED,
            CaseState.PAID_ELSEWHERE,
            CaseState.OPTED_OUT,
            CaseState.ABANDONED,
        }
    ),
    CaseState.RECOVERED: frozenset(),
    CaseState.PAID_ELSEWHERE: frozenset(),
    CaseState.OPTED_OUT: frozenset(),
    CaseState.ABANDONED: frozenset(),
    CaseState.ESCALATED: frozenset(),
    CaseState.CLOSED_NO_ACTION: frozenset(),
}


class IllegalTransition(ValueError):
    """A transition the state diagram does not draw."""


def can_advance(current: CaseState, target: CaseState) -> bool:
    return target in TRANSITIONS[CaseState(current)]


def advance(current: CaseState | str, target: CaseState | str) -> CaseState:
    """The next state, or an exception. There is no third option, deliberately."""
    current, target = CaseState(current), CaseState(target)
    if not can_advance(current, target):
        raise IllegalTransition(f"{current.value} cannot advance to {target.value}")
    return target


def is_terminal(state: CaseState | str) -> bool:
    return CaseState(state) in TERMINAL_STATES


def outcome_for(state: CaseState | str) -> str | None:
    return TERMINAL_OUTCOME.get(CaseState(state))


def terminal_target_for(state: CaseState | str) -> CaseState:
    """How a case in this state closes when the run ends or its TTL passes.

    The diagram draws ABANDONED only from ELIGIBLE, DEFERRED, LINK_CREATED and WAITING. A case
    still in DETECTED was never acted on at all, so it closes as CLOSED_NO_ACTION, which is the
    state the diagram gives for "nothing was done". Reaching for ABANDONED there would have been
    an illegal transition, and the state machine says so rather than allowing it quietly.
    """
    state = CaseState(state)
    if state in TERMINAL_STATES:
        return state
    if state == CaseState.DETECTED:
        return CaseState.CLOSED_NO_ACTION
    if state == CaseState.NUDGED:
        # NUDGED has no ABANDONED edge; it always passes through WAITING first.
        return CaseState.WAITING
    return CaseState.ABANDONED


@dataclass(frozen=True)
class CaseUpdate:
    """One transition, ready to write."""

    case_id: str
    state: CaseState
    outcome: str | None
    updated_at: int
    next_action_at: int | None = None
