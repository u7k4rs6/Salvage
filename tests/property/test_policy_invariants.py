"""Policy engine invariants, as property tests.

docs/02_TECHNICAL_ARCHITECTURE.md section 15 lists them:

  never two open links per order, never outside quiet hours, never over caps, never on a paid
  order, never without consent, amount always equals order amount

Each is a claim about every possible state, not about the states somebody thought to type out, so
each is a Hypothesis property over generated ActionContexts rather than an example test.

The last one, "amount always equals order amount", is not testable as a runtime property because
there is no amount anywhere in the action schema to compare against. It is tested structurally
instead: no params model in the menu has a field that could hold an amount, and no module in
salvage/execute reads an amount from model output. A property test over a field that cannot exist
would be theatre; a grep over the source is the real guarantee.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from salvage.decide import policy
from salvage.decide.menu import ALWAYS_ALLOWED, PARAMS_MODEL, ActionType
from salvage.decide.policy import (
    MAX_NUDGES_PER_7_DAYS,
    MAX_NUDGES_PER_INCIDENT,
    QUIET_HOURS_END,
    QUIET_HOURS_START,
    ActionContext,
    Decision,
)
from salvage.diagnose.reconcile import ACTION_CONFIDENCE_THRESHOLD
from salvage.sim.clock import IstCalendar
from salvage.taxonomy import HARD_DECLINE_REASONS, RootCause

REPO_ROOT = Path(__file__).resolve().parents[2]
CALENDAR = IstCalendar()

# A year of sim seconds, so quiet hours are exercised at every hour of the day.
_TIMESTAMPS = st.integers(min_value=1_700_000_000, max_value=1_700_000_000 + 365 * 86400)


def contexts(**overrides) -> st.SearchStrategy[ActionContext]:
    """ActionContexts with some fields pinned.

    Pinning rather than filtering with assume(). Filtering an action type out of five discards
    four fifths of everything Hypothesis generates, which it rightly complains about and which
    would leave the properties much less exercised than the example count suggests.
    """
    base = dict(_FIELD_STRATEGIES)
    base.update({key: st.just(value) for key, value in overrides.items()})
    return st.builds(ActionContext, **base)


_FIELD_STRATEGIES = dict(
    action_type=st.sampled_from(list(ActionType)),
    cause=st.sampled_from([c.value for c in RootCause]),
    confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    incident_id=st.just("inc_test"),
    now=_TIMESTAMPS,
    case_id=st.just("case_test"),
    order_paid=st.booleans(),
    order_created_at=_TIMESTAMPS,
    order_amount=st.integers(min_value=0, max_value=2_000_000),
    case_state=st.sampled_from(["DETECTED", "ELIGIBLE", "DEFERRED", "WAITING", "NUDGED"]),
    case_terminal=st.booleans(),
    open_link_exists=st.booleans(),
    last_attempt_reason=st.one_of(
        st.none(),
        st.sampled_from(sorted(HARD_DECLINE_REASONS)),
        st.sampled_from(["insufficient_funds", "bank_technical_error", "payment_timed_out"]),
    ),
    consent=st.booleans(),
    opted_out=st.booleans(),
    nudges_this_incident=st.integers(min_value=0, max_value=6),
    nudges_last_7_days=st.integers(min_value=0, max_value=9),
    segment_degraded=st.booleans(),
    segment_recovered=st.booleans(),
    kill_switch=st.booleans(),
    circuit_open=st.booleans(),
    circuit_detail=st.just(""),
)

_CONTEXTS = st.builds(ActionContext, **_FIELD_STRATEGIES)
_LINK = ActionType.SEND_RECOVERY_LINK

_SETTINGS = settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def _sends(verdict) -> bool:
    """Whether this verdict results in a message reaching a customer now.

    QUEUE sends later, at 09:00, and DEFER does not send at all. Only ALLOW sends now.
    """
    return verdict.decision == Decision.ALLOW


# -- never on a paid order -------------------------------------------------


@given(context=contexts(action_type=_LINK, order_paid=True))
@_SETTINGS
def test_never_acts_on_a_paid_order(context):
    verdict = policy.evaluate(context, CALENDAR)
    assert verdict.decision == Decision.REFUSE
    assert not _sends(verdict)


# -- never without consent -------------------------------------------------


@given(context=contexts(action_type=_LINK, consent=False))
@_SETTINGS
def test_never_sends_without_consent(context):
    assert not _sends(policy.evaluate(context, CALENDAR))


@given(context=contexts(action_type=_LINK, opted_out=True))
@_SETTINGS
def test_never_sends_to_an_opted_out_customer(context):
    assert not _sends(policy.evaluate(context, CALENDAR))


# -- never two open links per order ----------------------------------------


@given(context=contexts(action_type=_LINK, open_link_exists=True, order_paid=False))
@_SETTINGS
def test_never_creates_a_second_open_link_for_an_order(context):
    verdict = policy.evaluate(context, CALENDAR)
    assert verdict.decision == Decision.REFUSE


# -- never over caps -------------------------------------------------------


@given(
    context=contexts(action_type=_LINK),
    extra=st.integers(min_value=MAX_NUDGES_PER_INCIDENT, max_value=MAX_NUDGES_PER_INCIDENT + 4),
)
@_SETTINGS
def test_never_exceeds_the_per_incident_nudge_cap(context, extra):
    context = replace(context, nudges_this_incident=extra)
    assert not _sends(policy.evaluate(context, CALENDAR))


@given(
    context=contexts(action_type=_LINK),
    extra=st.integers(min_value=MAX_NUDGES_PER_7_DAYS, max_value=MAX_NUDGES_PER_7_DAYS + 4),
)
@_SETTINGS
def test_never_exceeds_the_rolling_seven_day_cap(context, extra):
    context = replace(context, nudges_last_7_days=extra)
    assert not _sends(policy.evaluate(context, CALENDAR))


# -- never outside quiet hours ---------------------------------------------


@given(context=contexts(action_type=_LINK))
@_SETTINGS
def test_never_sends_inside_quiet_hours(context):
    assume(CALENDAR.is_quiet_hours(context.now, QUIET_HOURS_START, QUIET_HOURS_END))
    verdict = policy.evaluate(context, CALENDAR)
    assert not _sends(verdict)
    if verdict.decision == Decision.QUEUE:
        # Queued for 09:00 IST, never dropped (docs/01_PRD.md section 9).
        assert verdict.scheduled_for is not None
        assert verdict.scheduled_for > context.now
        assert CALENDAR.hour_of_day(verdict.scheduled_for) == QUIET_HOURS_END
        assert not CALENDAR.is_quiet_hours(
            verdict.scheduled_for, QUIET_HOURS_START, QUIET_HOURS_END
        )


@given(now=_TIMESTAMPS)
@_SETTINGS
def test_the_quiet_hours_queue_target_is_always_the_next_nine_am(now):
    target = policy.next_quiet_hours_end(now, CALENDAR)
    assert target > now
    assert CALENDAR.hour_of_day(target) == QUIET_HOURS_END
    assert target - now <= 86400


# -- never into a still-degraded rail --------------------------------------


@given(context=contexts(action_type=_LINK, segment_degraded=True))
@_SETTINGS
def test_a_send_into_a_still_degraded_method_becomes_a_defer(context):
    verdict = policy.evaluate(context, CALENDAR)
    assert not _sends(verdict)
    if verdict.decision == Decision.DEFER:
        assert verdict.converted_to == ActionType.DEFER_UNTIL_RECOVERED


# -- hard declines ---------------------------------------------------------


@given(
    context=contexts(action_type=_LINK, order_paid=False, open_link_exists=False),
    reason=st.sampled_from(sorted(HARD_DECLINE_REASONS)),
)
@_SETTINGS
def test_never_retries_a_hard_decline(context, reason):
    context = replace(context, last_attempt_reason=reason, case_terminal=False)
    assume(context.now <= context.order_created_at + policy.ORDER_TTL_SECONDS)
    assert policy.evaluate(context, CALENDAR).decision == Decision.REFUSE


# -- kill switch and circuit breaker ---------------------------------------


@given(
    context=contexts(kill_switch=True),
    action=st.sampled_from([a for a in ActionType if a not in ALWAYS_ALLOWED]),
)
@_SETTINGS
def test_the_kill_switch_stops_every_outbound_action(context, action):
    context = replace(context, action_type=action)
    assert not _sends(policy.evaluate(context, CALENDAR))


@given(context=contexts(kill_switch=True, action_type=ActionType.ESCALATE_HUMAN))
@_SETTINGS
def test_the_kill_switch_does_not_stop_escalation(context):
    """Detection, diagnosis and escalation keep working (security doc section 6)."""
    assert policy.evaluate(context, CALENDAR).decision == Decision.ALLOW


@given(
    context=contexts(circuit_open=True),
    action=st.sampled_from([a for a in ActionType if a not in ALWAYS_ALLOWED]),
)
@_SETTINGS
def test_an_open_circuit_stops_outbound_actions(context, action):
    context = replace(context, action_type=action)
    assert not _sends(policy.evaluate(context, CALENDAR))


# -- matrix ----------------------------------------------------------------


@given(context=contexts(cause=RootCause.MERCHANT_CONFIG.value, action_type=_LINK))
@_SETTINGS
def test_a_merchant_config_incident_never_contacts_a_customer(context):
    """S4's required behaviour: escalate only, no customer contact, whatever else is true."""
    verdict = policy.evaluate(context, CALENDAR)
    assert verdict.decision == Decision.REFUSE
    assert policy.refused_for_matrix(verdict)


@given(context=contexts(cause=RootCause.UNKNOWN.value, action_type=_LINK))
@_SETTINGS
def test_an_unknown_cause_never_contacts_a_customer(context):
    assert policy.evaluate(context, CALENDAR).decision == Decision.REFUSE


@given(
    context=_CONTEXTS,
    action=st.sampled_from([a for a in ActionType if a not in ALWAYS_ALLOWED]),
    confidence=st.floats(min_value=0.0, max_value=ACTION_CONFIDENCE_THRESHOLD - 0.001),
)
@_SETTINGS
def test_below_the_confidence_threshold_nothing_customer_facing_happens(
    context, action, confidence
):
    context = replace(context, action_type=action, confidence=confidence)
    assert not _sends(policy.evaluate(context, CALENDAR))


@given(context=_CONTEXTS, action=st.sampled_from(sorted(ALWAYS_ALLOWED)))
@_SETTINGS
def test_escalation_and_no_action_are_always_allowed(context, action):
    context = replace(context, action_type=action)
    assert policy.evaluate(context, CALENDAR).decision == Decision.ALLOW


# -- every verdict is explainable ------------------------------------------


@given(context=_CONTEXTS)
@_SETTINGS
def test_every_verdict_records_at_least_one_gate_and_names_its_refusal(context):
    verdict = policy.evaluate(context, CALENDAR)
    assert verdict.gates
    for gate in verdict.gates:
        assert gate.rule
        assert gate.detail
    if verdict.decision == Decision.REFUSE:
        assert verdict.refusing_rule is not None


# -- amount always equals order amount -------------------------------------


_AMOUNT_FIELD = re.compile(r"amount|price|currency|discount|value_paise", re.IGNORECASE)


def test_no_action_params_model_can_express_an_amount():
    """docs/03_SECURITY_AND_ACCESS.md section 6: the action schema cannot express an amount."""
    for action, model in PARAMS_MODEL.items():
        for field_name in model.model_fields:
            assert not _AMOUNT_FIELD.search(field_name), f"{action.value}.{field_name}"


def test_the_planner_output_schema_cannot_express_an_amount():
    from salvage.decide.planner import Plan, PlannedAction

    for model in (Plan, PlannedAction):
        for field_name in model.model_fields:
            assert not _AMOUNT_FIELD.search(field_name), f"{model.__name__}.{field_name}"


def test_no_executor_code_path_reads_an_amount_from_model_output():
    """The structural half of "amount always equals order amount".

    An amount that came from the model would have to be read out of a params dict or a plan. The
    executor reads `order["amount"]` and nothing else, so this greps for the shapes that would
    indicate otherwise.
    """
    forbidden = (
        re.compile(r"params\s*\[\s*['\"]amount"),
        re.compile(r"params\.get\(\s*['\"]amount"),
        re.compile(r"plan\s*\[\s*['\"]amount"),
        re.compile(r"\.params\.amount\b"),
        re.compile(r"action\s*\[\s*['\"]amount"),
    )
    findings = []
    for path in sorted((REPO_ROOT / "salvage").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pattern in forbidden:
                if pattern.search(line):
                    findings.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    assert findings == [], "amount must never come from model output: " + "; ".join(findings)


def test_that_grep_would_catch_a_real_violation():
    forbidden = re.compile(r"params\s*\[\s*['\"]amount")
    assert forbidden.search('amount = params["amount"]')
    assert not forbidden.search('amount = order["amount"]')
