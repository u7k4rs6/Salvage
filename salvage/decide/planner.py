"""LLM planner.

docs/02_TECHNICAL_ARCHITECTURE.md section 7:

  The LLM receives the reconciled diagnosis, the menu with per-action descriptions, the
  cause-to-action matrix, and the counts of eligible customers by consent and alternate-method
  availability. Output schema:

    incident_id
    actions: list[{type: enum, scope: all_affected | consented_with_alternate | only_failing_method,
                   params}]
    rationale: str, max 400 chars

The model proposes. Code decides and acts. Nothing this module returns reaches Razorpay or a
customer without passing salvage/decide/policy.py first, and the policy engine runs before every
individual action rather than once per plan.

What crosses to the model here is counts, not customers: how many affected customers have consent,
how many have an alternate method. No customer id, no contact, no per-customer amount
(docs/03_SECURITY_AND_ACCESS.md section 7).
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, field_validator

from salvage.decide.menu import (
    ALWAYS_ALLOWED,
    ActionType,
    Scope,
    matrix_entry,
    required_actions,
    validate_params,
)
from salvage.llm.provider import LLMError, LLMProvider

MAX_RATIONALE_CHARS = 400
MAX_ACTIONS = 5


class EligibilityCounts(BaseModel):
    """Counts only. This is the whole of what the model learns about the customers."""

    model_config = {"extra": "forbid"}

    affected_orders: int = 0
    unpaid_orders: int = 0
    consented: int = 0
    consented_with_alternate: int = 0
    opted_out: int = 0
    hard_declined: int = 0
    above_value_threshold: int = 0


class PlannedAction(BaseModel):
    model_config = {"extra": "forbid"}

    type: ActionType
    scope: Scope = Scope.ALL_AFFECTED
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("params")
    @classmethod
    def _params_are_a_flat_object(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("params must be an object")
        return value

    def validated_params(self) -> BaseModel:
        """Params against this action's own model. Raises on an unknown field."""
        return validate_params(self.type, self.params)


class Plan(BaseModel):
    """The planner's output schema, exactly as Architecture section 7 specifies it."""

    model_config = {"extra": "forbid"}

    incident_id: str = Field(min_length=1, max_length=128)
    actions: list[PlannedAction] = Field(default_factory=list, max_length=MAX_ACTIONS)
    rationale: str = Field(default="", max_length=MAX_RATIONALE_CHARS)


SYSTEM_PROMPT = """\
You are planning the response to one payment incident for an Indian merchant on Razorpay. You have
already been told the diagnosed cause. Choose actions from the menu you are given and nothing else.

The menu is closed. These are the only five things that can happen:
  STEER_METHOD: set a checkout display hint that hides or de-prioritises the failing instrument
    and surfaces alternatives. Affects the storefront and recovery links for the affected segment
    only, and expires when the incident closes.
  SEND_RECOVERY_LINK: create a Razorpay Payment Link for a failed order and send a templated
    message through the merchant's own channel. The link is always for the exact original order
    amount. You cannot set an amount, a discount or an expiry; those are not fields you have.
  DEFER_UNTIL_RECOVERED: hold messages for affected customers until their segment recovers, then
    send. Use this when contacting somebody now would push them back into a rail that is still
    broken.
  ESCALATE_HUMAN: open a ticket with the evidence and a proposed action, and wait. Nothing
    customer-facing happens until a person decides.
  NO_ACTION: record that nothing will be done, with the reason.

Scopes: all_affected, consented_with_alternate, only_failing_method.

Hard rules. Breaking any of them causes the action to be refused and the incident escalated, so
there is nothing to gain from trying:
  You cannot change what a customer owes. There is no refund, no discount, no partial payment and
    no amount field anywhere in the menu.
  A cause the matrix marks "no" for an action means that action will be refused for that cause.
  Merchant-side and unknown causes get no customer contact at all. The merchant has to fix
    something; messaging customers about it is noise at best.
  Consent, opt-out, quiet hours and frequency caps are enforced in code after you answer. Do not
    reason about individual customers; you have only counts.
  Answer with JSON only, matching the schema you were given. Keep the rationale under 400
    characters.
"""


def build_planner_prompt(
    *,
    incident_id: str,
    segment_key: str,
    cause: str,
    confidence: float,
    counts: EligibilityCounts,
    segment_recovered: bool,
    value_threshold_paise: int,
) -> str:
    allowed_lines = []
    for action in ActionType:
        entry = matrix_entry(cause, action)
        if action in ALWAYS_ALLOWED:
            allowed_lines.append(f"  {action.value}: allowed (always available)")
            continue
        if not entry.allowed:
            allowed_lines.append(f"  {action.value}: NOT allowed for {cause}")
            continue
        conditions = []
        if entry.requires_segment_recovered:
            conditions.append("only after the segment has recovered")
        if entry.requires_value_threshold:
            conditions.append(f"only above {value_threshold_paise} paise")
        if entry.single_nudge_only:
            conditions.append("single nudge only")
        if entry.note:
            conditions.append(entry.note)
        # Deduplicate while keeping order: requires_segment_recovered and the matrix note say the
        # same thing for gateway_degradation, and printing it twice reads like a bug to a model.
        conditions = list(dict.fromkeys(conditions))
        suffix = f" ({'; '.join(conditions)})" if conditions else ""
        allowed_lines.append(f"  {action.value}: allowed{suffix}")

    required = required_actions(cause)
    required_text = (
        ", ".join(a.value for a in required) if required else "none beyond what you choose"
    )

    return "\n".join(
        [
            f"incident_id: {incident_id}",
            f"segment: {segment_key}",
            f"diagnosed cause: {cause}",
            f"diagnosis confidence: {confidence:.2f}",
            f"segment has recovered: {segment_recovered}",
            "",
            "What the cause-to-action matrix allows here:",
            *allowed_lines,
            f"Required for this cause: {required_text}",
            "",
            "Eligible customers, as counts only:",
            f"  affected orders: {counts.affected_orders}",
            f"  still unpaid: {counts.unpaid_orders}",
            f"  consented: {counts.consented}",
            f"  consented and have an alternate payment method: {counts.consented_with_alternate}",
            f"  opted out: {counts.opted_out}",
            f"  last attempt was a hard decline: {counts.hard_declined}",
            f"  above the value threshold: {counts.above_value_threshold}",
            "",
            "Choose the actions. Answer with JSON only.",
        ]
    )


def default_plan(incident_id: str, cause: str, detail: str = "") -> Plan:
    """The plan used when there is no model, or the model failed.

    Escalation, always. A planner that cannot plan must not fall back to doing something to
    customers; it falls back to asking a person. This is also the rules-only mode's plan, which is
    why the rules-only ablation reports diagnosis accuracy and not recovered revenue.
    """
    reason = detail or f"no model plan available for a {cause} incident"
    return Plan(
        incident_id=incident_id,
        actions=[
            PlannedAction(
                type=ActionType.ESCALATE_HUMAN,
                scope=Scope.ALL_AFFECTED,
                params={"reason": reason[:300]},
            )
        ],
        rationale=reason[:MAX_RATIONALE_CHARS],
    )


def plan_incident(
    provider: LLMProvider | None,
    *,
    incident_id: str,
    segment_key: str,
    cause: str,
    confidence: float,
    counts: EligibilityCounts,
    segment_recovered: bool,
    value_threshold_paise: int,
    conn=None,
) -> tuple[Plan, str | None]:
    """(plan, error). Never raises: a planning failure escalates like any other refusal."""
    if provider is None:
        return default_plan(incident_id, cause, "no planner configured"), None

    prompt = build_planner_prompt(
        incident_id=incident_id,
        segment_key=segment_key,
        cause=cause,
        confidence=confidence,
        counts=counts,
        segment_recovered=segment_recovered,
        value_threshold_paise=value_threshold_paise,
    )
    try:
        plan = provider.complete(SYSTEM_PROMPT, prompt, Plan, conn=conn)
    except LLMError as exc:
        return default_plan(incident_id, cause, f"planner failed: {exc}"), str(exc)

    # The model may return a different incident id. It does not get to choose which incident it is
    # planning for, so the caller's id wins and the mismatch is recorded.
    if plan.incident_id != incident_id:
        plan = plan.model_copy(update={"incident_id": incident_id})

    # Params are validated per action here rather than in the schema, because the schema has to
    # accept a generic object for the model to fill. An action whose params do not validate is
    # dropped and the drop is visible in the returned error.
    kept, dropped = [], []
    for action in plan.actions:
        try:
            action.validated_params()
        except Exception as exc:  # noqa: BLE001 - any validation failure drops the action
            dropped.append(f"{action.type.value}: {exc}")
            continue
        kept.append(action)
    if dropped:
        plan = plan.model_copy(update={"actions": kept})
        return plan, "dropped invalid actions: " + "; ".join(dropped)
    return plan, None


def plan_json(plan: Plan) -> str:
    return json.dumps(json.loads(plan.model_dump_json()), sort_keys=True)
