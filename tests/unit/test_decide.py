"""Action menu, planner and the policy engine's database-backed half.

The policy engine's invariants are property tests in tests/property/test_policy_invariants.py.
This file covers the parts that read state, plus the menu's schemas and the matrix.
"""

from __future__ import annotations

import json

import pydantic
import pytest

from salvage import repo
from salvage.decide.menu import (
    ALWAYS_ALLOWED,
    CAUSE_ACTION_MATRIX,
    ActionType,
    SendRecoveryLinkParams,
    SteerMethodParams,
    matrix_entry,
    required_actions,
    validate_params,
)
from salvage.decide.planner import (
    EligibilityCounts,
    Plan,
    PlannedAction,
    build_planner_prompt,
    default_plan,
    plan_incident,
)
from salvage.decide.policy import (
    CIRCUIT_MIN_ACTIONS,
    Decision,
    build_context,
    circuit_state,
    evaluate,
)
from salvage.decide.policy import (
    ActionType as PolicyActionType,
)
from salvage.taxonomy import Method, RootCause

# -- menu ------------------------------------------------------------------


def test_the_matrix_covers_every_cause_and_every_action():
    for cause in RootCause:
        assert cause.value in CAUSE_ACTION_MATRIX, cause
        for action in ActionType:
            assert action in CAUSE_ACTION_MATRIX[cause.value]


def test_the_matrix_matches_the_documented_table():
    """Architecture section 7's table, cell by cell for the rows that forbid things."""
    forbidden = {
        (RootCause.GATEWAY_DEGRADATION.value, ActionType.STEER_METHOD),
        (RootCause.MERCHANT_CONFIG.value, ActionType.STEER_METHOD),
        (RootCause.MERCHANT_CONFIG.value, ActionType.SEND_RECOVERY_LINK),
        (RootCause.MERCHANT_CONFIG.value, ActionType.DEFER_UNTIL_RECOVERED),
        (RootCause.CUSTOMER_SIDE.value, ActionType.STEER_METHOD),
        (RootCause.CUSTOMER_SIDE.value, ActionType.DEFER_UNTIL_RECOVERED),
        (RootCause.UNKNOWN.value, ActionType.STEER_METHOD),
        (RootCause.UNKNOWN.value, ActionType.SEND_RECOVERY_LINK),
        (RootCause.UNKNOWN.value, ActionType.DEFER_UNTIL_RECOVERED),
    }
    for cause, action in forbidden:
        assert not matrix_entry(cause, action).allowed, f"{cause}/{action.value}"

    assert matrix_entry(
        RootCause.GATEWAY_DEGRADATION.value, ActionType.SEND_RECOVERY_LINK
    ).requires_segment_recovered
    assert matrix_entry(
        RootCause.CUSTOMER_SIDE.value, ActionType.SEND_RECOVERY_LINK
    ).requires_value_threshold


def test_escalation_is_required_where_the_table_says_required():
    for cause in (
        RootCause.MERCHANT_CONFIG.value,
        RootCause.UNKNOWN.value,
        RootCause.GATEWAY_DEGRADATION.value,
    ):
        assert ActionType.ESCALATE_HUMAN in required_actions(cause)


def test_an_unknown_cause_string_allows_nothing_but_escalation():
    assert not matrix_entry("something_new", ActionType.SEND_RECOVERY_LINK).allowed
    assert matrix_entry("something_new", ActionType.ESCALATE_HUMAN).allowed
    assert {ActionType.ESCALATE_HUMAN, ActionType.NO_ACTION} == ALWAYS_ALLOWED


def test_the_recovery_link_params_have_exactly_one_field():
    assert set(SendRecoveryLinkParams.model_fields) == {"case_id"}


def test_params_reject_an_invented_amount_field():
    with pytest.raises(pydantic.ValidationError):
        validate_params(ActionType.SEND_RECOVERY_LINK, {"case_id": "c", "amount": 100})


def test_steer_cannot_hide_every_method():
    with pytest.raises(pydantic.ValidationError, match="every payment method"):
        SteerMethodParams(hide_methods=list(Method))


def test_steer_cannot_both_hide_and_prefer_a_method():
    with pytest.raises(pydantic.ValidationError, match="both hidden and preferred"):
        SteerMethodParams(hide_methods=[Method.UPI], prefer_methods=[Method.UPI])


# -- planner ---------------------------------------------------------------


def _counts() -> EligibilityCounts:
    return EligibilityCounts(
        affected_orders=20, unpaid_orders=20, consented=14, consented_with_alternate=8
    )


def test_the_planner_prompt_carries_counts_and_no_customer_identity():
    prompt = build_planner_prompt(
        incident_id="inc_1",
        segment_key="upi:upi_handle:okhdfcbank",
        cause=RootCause.ISSUER_OUTAGE.value,
        confidence=0.8,
        counts=_counts(),
        segment_recovered=False,
        value_threshold_paise=150000,
    )
    assert "consented and have an alternate payment method: 8" in prompt
    assert "cust_" not in prompt
    assert "@" not in prompt
    assert "order_" not in prompt


def test_the_planner_prompt_states_what_the_matrix_forbids():
    prompt = build_planner_prompt(
        incident_id="inc_1",
        segment_key="netbanking",
        cause=RootCause.MERCHANT_CONFIG.value,
        confidence=0.9,
        counts=_counts(),
        segment_recovered=False,
        value_threshold_paise=150000,
    )
    assert "SEND_RECOVERY_LINK: NOT allowed for merchant_config" in prompt
    assert "Required for this cause: ESCALATE_HUMAN" in prompt


def test_a_condition_is_not_printed_twice():
    prompt = build_planner_prompt(
        incident_id="inc_1",
        segment_key="all",
        cause=RootCause.GATEWAY_DEGRADATION.value,
        confidence=0.9,
        counts=_counts(),
        segment_recovered=False,
        value_threshold_paise=150000,
    )
    line = next(row for row in prompt.splitlines() if "SEND_RECOVERY_LINK" in row)
    assert line.count("only after the segment has recovered") == 1


def test_no_planner_means_escalate_not_act():
    plan, error = plan_incident(
        None,
        incident_id="inc_1",
        segment_key="upi",
        cause=RootCause.ISSUER_OUTAGE.value,
        confidence=0.9,
        counts=_counts(),
        segment_recovered=False,
        value_threshold_paise=150000,
    )
    assert error is None
    assert [a.type for a in plan.actions] == [ActionType.ESCALATE_HUMAN]


def test_a_failing_planner_escalates_rather_than_raising():
    from salvage.llm.provider import FixtureProvider

    plan, error = plan_incident(
        FixtureProvider(strict=True),
        incident_id="inc_1",
        segment_key="upi",
        cause=RootCause.ISSUER_OUTAGE.value,
        confidence=0.9,
        counts=_counts(),
        segment_recovered=False,
        value_threshold_paise=150000,
    )
    assert error is not None
    assert [a.type for a in plan.actions] == [ActionType.ESCALATE_HUMAN]


def test_the_default_plan_never_contacts_a_customer():
    plan = default_plan("inc_1", RootCause.UNKNOWN.value)
    assert all(a.type in ALWAYS_ALLOWED for a in plan.actions)


def test_a_plan_cannot_carry_more_than_five_actions():
    with pytest.raises(pydantic.ValidationError):
        Plan(
            incident_id="inc_1",
            actions=[
                PlannedAction(type=ActionType.NO_ACTION, params={"reason": "x"}) for _ in range(6)
            ],
        )


def test_a_plan_action_with_bad_params_is_dropped_not_executed():
    """A model that invents a field loses that action, and the drop is reported."""
    action = PlannedAction(type=ActionType.SEND_RECOVERY_LINK, params={"amount": 5000})
    with pytest.raises(pydantic.ValidationError):
        action.validated_params()


# -- policy over the database ---------------------------------------------


def _seed_case(conn, *, consent: int = 1, opted_out: int | None = None) -> dict:
    repo.insert_customer(
        conn,
        {
            "id": "cust_1",
            "ref_hash": "h" * 64,
            "consent": consent,
            "locale": "en",
            "typical_amount": 200000,
            "opted_out_at": opted_out,
            "alt_method": "card",
            "created_at": 0,
        },
    )
    repo.upsert_order(
        conn,
        {
            "id": "order_1",
            "customer_id": "cust_1",
            "amount": 200000,
            "status": "attempted",
            "source": "sim",
            "created_at": 1_700_000_000,
        },
    )
    repo.upsert_attempt(
        conn,
        {
            "id": "pay_1",
            "order_id": "order_1",
            "customer_id": "cust_1",
            "method": "upi",
            "status": "failed",
            "error_reason": "bank_technical_error",
            "created_at": 1_700_000_000,
            "raw_json": "{}",
        },
    )
    case = {
        "id": "case_1",
        "order_id": "order_1",
        "customer_id": "cust_1",
        "incident_id": "inc_1",
        "state": "DETECTED",
        "attempts": 0,
        "link_id": None,
        "link_url": None,
        "next_action_at": None,
        "ttl_at": 1_700_000_000 + 72 * 3600,
        "outcome": None,
        "updated_at": 1_700_000_000,
    }
    repo.insert_case(conn, case)
    return case


def _incident(cause: str = RootCause.ISSUER_OUTAGE.value, confidence: float = 0.9) -> dict:
    return {
        "id": "inc_1",
        "segment_key": "upi:upi_handle:okhdfcbank",
        "opened_at": 1_700_000_000,
        "closed_at": None,
        "root_cause": cause,
        "confidence": confidence,
    }


def test_build_context_reads_the_customer_and_the_order(conn):
    repo.insert_incident(
        conn,
        {
            "id": "inc_1",
            "segment_key": "upi",
            "opened_at": 1_700_000_000,
            "at_risk_amount": 0,
            "status": "open",
            "affected_scope_json": "[]",
        },
    )
    case = _seed_case(conn)
    context = build_context(
        conn,
        action_type=PolicyActionType.SEND_RECOVERY_LINK,
        incident=_incident(),
        now=1_700_000_600,
        case=case,
    )
    assert context.consent is True
    assert context.opted_out is False
    assert context.order_paid is False
    assert context.order_amount == 200000
    assert context.last_attempt_reason == "bank_technical_error"
    assert context.nudges_this_incident == 0


def test_a_paid_order_is_seen_by_the_gate(conn):
    repo.insert_incident(
        conn,
        {
            "id": "inc_1",
            "segment_key": "upi",
            "opened_at": 1_700_000_000,
            "at_risk_amount": 0,
            "status": "open",
            "affected_scope_json": "[]",
        },
    )
    case = _seed_case(conn)
    repo.mark_order_paid(conn, "order_1", 1_700_000_300)
    context = build_context(
        conn,
        action_type=PolicyActionType.SEND_RECOVERY_LINK,
        incident=_incident(),
        now=1_700_000_600,
        case=case,
    )
    assert context.order_paid is True
    assert evaluate(context).decision == Decision.REFUSE


def test_the_circuit_breaker_trips_on_a_high_outbound_failure_rate(conn):
    repo.insert_incident(
        conn,
        {
            "id": "inc_1",
            "segment_key": "upi",
            "opened_at": 0,
            "at_risk_amount": 0,
            "status": "open",
            "affected_scope_json": "[]",
        },
    )
    now = 1_700_000_000
    for index in range(CIRCUIT_MIN_ACTIONS + 2):
        repo.insert_action(
            conn,
            {
                "id": f"act_{index}",
                "case_id": None,
                "incident_id": "inc_1",
                "type": "SEND_RECOVERY_LINK",
                "params_json": "{}",
                "gate_json": "[]",
                "status": "failed" if index % 2 == 0 else "executed",
                "rzp_request_id": None,
                "rzp_response_json": None,
                "executed_at": now - 60,
            },
        )
    state = circuit_state(conn, "inc_1", now)
    assert state.open
    assert "above 30%" in state.detail


def test_the_circuit_breaker_stays_closed_below_the_minimum_action_count(conn):
    repo.insert_incident(
        conn,
        {
            "id": "inc_1",
            "segment_key": "upi",
            "opened_at": 0,
            "at_risk_amount": 0,
            "status": "open",
            "affected_scope_json": "[]",
        },
    )
    now = 1_700_000_000
    for index in range(3):
        repo.insert_action(
            conn,
            {
                "id": f"act_{index}",
                "case_id": None,
                "incident_id": "inc_1",
                "type": "SEND_RECOVERY_LINK",
                "params_json": "{}",
                "gate_json": "[]",
                "status": "failed",
                "rzp_request_id": None,
                "rzp_response_json": None,
                "executed_at": now - 60,
            },
        )
    assert not circuit_state(conn, "inc_1", now).open


def test_gate_results_serialise_to_the_documented_shape(conn):
    context = build_context(
        conn,
        action_type=PolicyActionType.ESCALATE_HUMAN,
        incident=_incident(),
        now=1_700_000_000,
    )
    verdict = evaluate(context)
    payload = json.loads(json.dumps(verdict.gates_json()))
    for gate in payload:
        assert set(gate) == {"rule", "passed", "detail"}


def test_a_planned_recovery_link_survives_validation_without_a_case_id():
    """The planner is asked for an action and a scope, and the executor fans that out over cases.
    A case id is therefore not something the planner can supply, and requiring one at plan time
    dropped every SEND_RECOVERY_LINK a real model proposed. That went unnoticed for a milestone
    because there was no model to propose one: with no provider the agent escalates instead of
    planning, so the path was never taken."""

    class _Provider:
        name = "gemini"
        model = "test"

        def complete(self, system, user, schema, *, conn=None):
            del system, user, conn
            return schema.model_validate(
                {
                    "incident_id": "inc_1",
                    "actions": [
                        {"type": "SEND_RECOVERY_LINK", "scope": "consented_with_alternate"}
                    ],
                    "rationale": "steer the consented customers to a working rail",
                }
            )

    plan, error = plan_incident(
        _Provider(),
        incident_id="inc_1",
        segment_key="upi:upi_handle:okhdfcbank",
        cause="issuer_outage",
        confidence=0.9,
        counts=EligibilityCounts(
            affected_orders=20,
            unpaid_orders=20,
            consented=9,
            consented_with_alternate=6,
            above_value_threshold=7,
            hard_declined=0,
            opted_out=0,
        ),
        segment_recovered=False,
        value_threshold_paise=50000,
    )
    assert error is None, error
    assert [action.type for action in plan.actions] == [ActionType.SEND_RECOVERY_LINK]


def test_a_planned_action_that_invents_a_field_is_still_dropped():
    """The plan-time check exists to stop an invented `amount` reaching the executor, and the
    case-id placeholder must not weaken it."""

    class _Provider:
        name = "gemini"
        model = "test"

        def complete(self, system, user, schema, *, conn=None):
            del system, user, conn
            return schema.model_validate(
                {
                    "incident_id": "inc_1",
                    "actions": [
                        {
                            "type": "SEND_RECOVERY_LINK",
                            "scope": "all_affected",
                            "params": {"amount": 100, "discount_percent": 10},
                        }
                    ],
                    "rationale": "offer a discount",
                }
            )

    plan, error = plan_incident(
        _Provider(),
        incident_id="inc_1",
        segment_key="upi",
        cause="issuer_outage",
        confidence=0.9,
        counts=EligibilityCounts(
            affected_orders=1,
            unpaid_orders=1,
            consented=1,
            consented_with_alternate=1,
            above_value_threshold=1,
            hard_declined=0,
            opted_out=0,
        ),
        segment_recovered=False,
        value_threshold_paise=50000,
    )
    # The action is dropped, and because nothing survives, the plan falls back to escalating
    # rather than to silence. See
    # test_a_plan_whose_actions_are_all_dropped_escalates_rather_than_falling_silent.
    assert [action.type for action in plan.actions] == [ActionType.ESCALATE_HUMAN]
    assert error is not None and "amount" in error


def _provider_returning(actions, rationale="the merchant's own configuration is refusing these"):
    class _Provider:
        name = "gemini"
        model = "test"

        def complete(self, system, user, schema, *, conn=None):
            del system, user, conn
            return schema.model_validate(
                {"incident_id": "inc_1", "actions": actions, "rationale": rationale}
            )

    return _Provider()


def _plan_with(provider, cause="merchant_config"):
    return plan_incident(
        provider,
        incident_id="inc_1",
        segment_key="netbanking",
        cause=cause,
        confidence=0.95,
        counts=EligibilityCounts(
            affected_orders=20,
            unpaid_orders=20,
            consented=9,
            consented_with_alternate=6,
            above_value_threshold=7,
            hard_declined=0,
            opted_out=0,
        ),
        segment_recovered=False,
        value_threshold_paise=50000,
    )


def test_an_escalation_without_a_reason_takes_the_plan_rationale():
    """Gemini escalated the S4 misconfiguration and wrote its reasoning in the plan's rationale,
    leaving the action's params empty. EscalateHumanParams requires a reason, so the action was
    dropped and the agent answered a merchant misconfiguration with silence, which is the one
    response the design does not allow. An action is not wrong for putting its explanation in the
    field next door."""
    plan, error = _plan_with(
        _provider_returning([{"type": "ESCALATE_HUMAN", "scope": "all_affected"}])
    )
    assert error is None, error
    assert [action.type for action in plan.actions] == [ActionType.ESCALATE_HUMAN]
    assert plan.actions[0].params["reason"] == "the merchant's own configuration is refusing these"


def test_a_plan_whose_actions_are_all_dropped_escalates_rather_than_falling_silent():
    """A planner that cannot plan asks a person. That is what default_plan is for, and it was
    only reached when the provider was absent or raised, never when every action it proposed was
    thrown away by validation."""
    plan, error = _plan_with(
        _provider_returning(
            [{"type": "SEND_RECOVERY_LINK", "scope": "all_affected", "params": {"amount": 100}}]
        )
    )
    assert error is not None and "amount" in error
    assert [action.type for action in plan.actions] == [ActionType.ESCALATE_HUMAN]
    assert plan.actions[0].params["reason"]
