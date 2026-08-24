"""The per-order state machine, against the diagram in Architecture section 8."""

from __future__ import annotations

import pytest

from salvage.execute.workflow import (
    TERMINAL_STATES,
    TRANSITIONS,
    CaseState,
    IllegalTransition,
    advance,
    is_terminal,
    outcome_for,
    terminal_target_for,
)


def test_every_state_in_the_enum_has_a_transition_entry():
    assert set(TRANSITIONS) == set(CaseState)


def test_the_happy_path_from_the_diagram():
    state = CaseState.DETECTED
    for target in (
        CaseState.ELIGIBLE,
        CaseState.LINK_CREATED,
        CaseState.NUDGED,
        CaseState.WAITING,
        CaseState.RECOVERED,
    ):
        state = advance(state, target)
    assert state == CaseState.RECOVERED
    assert is_terminal(state)


def test_the_defer_loop_from_the_diagram():
    state = advance(CaseState.DETECTED, CaseState.ELIGIBLE)
    state = advance(state, CaseState.DEFERRED)
    state = advance(state, CaseState.ELIGIBLE)
    assert state == CaseState.ELIGIBLE


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (CaseState.DETECTED, CaseState.ABANDONED),
        (CaseState.DETECTED, CaseState.RECOVERED),
        (CaseState.DEFERRED, CaseState.CLOSED_NO_ACTION),
        (CaseState.RECOVERED, CaseState.NUDGED),
        (CaseState.ABANDONED, CaseState.ELIGIBLE),
        (CaseState.LINK_CREATED, CaseState.RECOVERED),
    ],
)
def test_transitions_the_diagram_does_not_draw_are_refused(current, target):
    with pytest.raises(IllegalTransition):
        advance(current, target)


def test_terminal_states_have_no_outgoing_edges():
    for state in TERMINAL_STATES:
        assert TRANSITIONS[state] == frozenset()
        assert outcome_for(state) is not None


def test_non_terminal_states_have_no_outcome():
    for state in CaseState:
        if state not in TERMINAL_STATES:
            assert outcome_for(state) is None


def test_terminal_target_never_produces_an_illegal_transition():
    """Every state can be closed out by a path the diagram actually draws."""
    for state in CaseState:
        current = state
        for _ in range(4):
            if is_terminal(current):
                break
            current = advance(current, terminal_target_for(current))
        assert is_terminal(current), f"{state.value} could not be closed out"


def test_a_case_that_was_never_acted_on_closes_as_no_action_not_abandoned():
    assert terminal_target_for(CaseState.DETECTED) == CaseState.CLOSED_NO_ACTION
    assert terminal_target_for(CaseState.WAITING) == CaseState.ABANDONED


def test_every_state_is_reachable_from_detected():
    reachable = {CaseState.DETECTED}
    frontier = [CaseState.DETECTED]
    while frontier:
        state = frontier.pop()
        for target in TRANSITIONS[state]:
            if target not in reachable:
                reachable.add(target)
                frontier.append(target)
    assert reachable == set(CaseState)
