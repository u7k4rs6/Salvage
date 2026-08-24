"""Allowlisted action menu and the cause-to-action matrix.

docs/01_PRD.md section 8 and docs/02_TECHNICAL_ARCHITECTURE.md section 7.

The single most important property in this file, from docs/03_SECURITY_AND_ACCESS.md section 6:

  The action schema cannot express an amount. SEND_RECOVERY_LINK params carry a case id; the
  executor reads the order amount from the database. There is no code path that takes an amount
  from model output.

`SendRecoveryLinkParams` therefore has one field, and a test asserts that no params model anywhere
in the menu has a field whose name mentions an amount, a price or a currency. That test is the
enforcement; this docstring is only the explanation.

The allowlist is closed. `ActionType` is a StrEnum and the planner's output is validated against
it, so an action the model invents fails validation and opens an escalation rather than reaching
the executor.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from salvage.taxonomy import Method, RootCause


class ActionType(StrEnum):
    STEER_METHOD = "STEER_METHOD"
    SEND_RECOVERY_LINK = "SEND_RECOVERY_LINK"
    DEFER_UNTIL_RECOVERED = "DEFER_UNTIL_RECOVERED"
    ESCALATE_HUMAN = "ESCALATE_HUMAN"
    NO_ACTION = "NO_ACTION"


class Scope(StrEnum):
    """Who a planned action applies to. Architecture section 7's planner output schema."""

    ALL_AFFECTED = "all_affected"
    CONSENTED_WITH_ALTERNATE = "consented_with_alternate"
    ONLY_FAILING_METHOD = "only_failing_method"


# ---------------------------------------------------------------------------
# Params
# ---------------------------------------------------------------------------


class SteerMethodParams(BaseModel):
    """A checkout display hint. Applies only to the affected segment (PRD section 8)."""

    model_config = {"extra": "forbid"}

    hide_methods: list[Method] = Field(default_factory=list, max_length=4)
    prefer_methods: list[Method] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def _must_leave_something(self) -> SteerMethodParams:
        """Hiding every method is not steering, it is closing the shop."""
        if len(set(self.hide_methods)) >= len(Method):
            raise ValueError("STEER_METHOD may not hide every payment method")
        overlap = set(self.hide_methods) & set(self.prefer_methods)
        if overlap:
            raise ValueError(f"a method cannot be both hidden and preferred: {sorted(overlap)}")
        return self


class SendRecoveryLinkParams(BaseModel):
    """A recovery link for one case.

    One field. There is no amount, no currency, no discount, no expiry override. The executor
    reads the order amount from the database and sets expiry to the case TTL.
    """

    model_config = {"extra": "forbid"}

    case_id: str = Field(min_length=1, max_length=64)


class DeferParams(BaseModel):
    model_config = {"extra": "forbid"}

    case_id: str | None = Field(default=None, max_length=64)


class EscalateHumanParams(BaseModel):
    model_config = {"extra": "forbid"}

    reason: str = Field(min_length=1, max_length=300)


class NoActionParams(BaseModel):
    model_config = {"extra": "forbid"}

    reason: str = Field(min_length=1, max_length=300)


PARAMS_MODEL: dict[ActionType, type[BaseModel]] = {
    ActionType.STEER_METHOD: SteerMethodParams,
    ActionType.SEND_RECOVERY_LINK: SendRecoveryLinkParams,
    ActionType.DEFER_UNTIL_RECOVERED: DeferParams,
    ActionType.ESCALATE_HUMAN: EscalateHumanParams,
    ActionType.NO_ACTION: NoActionParams,
}


class MessageSlots(BaseModel):
    """The only free text the model contributes to a customer-facing message.

    Architecture section 8: the planner returns slots and the template is rendered locally after
    the model returns. Every field is length-capped, and the template validator rejects the
    rendered result if it contains a promise, a discount or urgency language.
    """

    model_config = {"extra": "forbid"}

    alternate_method_suggestion: str | None = Field(default=None, max_length=40)
    reason_summary: str | None = Field(default=None, max_length=120)


# ---------------------------------------------------------------------------
# Cause to action matrix
# ---------------------------------------------------------------------------


class MatrixEntry(BaseModel):
    """One cell of the matrix in Architecture section 7."""

    model_config = {"extra": "forbid"}

    allowed: bool
    # Conditions the policy engine checks on top of the cell being allowed at all.
    requires_segment_recovered: bool = False
    requires_value_threshold: bool = False
    single_nudge_only: bool = False
    required: bool = False
    note: str = ""


_YES = MatrixEntry(allowed=True)
_NO = MatrixEntry(allowed=False)

# Architecture section 7's table, transcribed. "optional" and "yes" both mean allowed; the
# distinction there is advice to the planner, not a gate, so it is carried in `note`.
CAUSE_ACTION_MATRIX: dict[str, dict[ActionType, MatrixEntry]] = {
    RootCause.ISSUER_OUTAGE.value: {
        ActionType.STEER_METHOD: _YES,
        ActionType.SEND_RECOVERY_LINK: MatrixEntry(
            allowed=True, note="consented customers with an alternate method"
        ),
        ActionType.DEFER_UNTIL_RECOVERED: _YES,
        ActionType.ESCALATE_HUMAN: MatrixEntry(allowed=True, note="optional"),
        ActionType.NO_ACTION: _YES,
    },
    RootCause.AUTH_FAILURE_BIN.value: {
        ActionType.STEER_METHOD: _YES,
        ActionType.SEND_RECOVERY_LINK: MatrixEntry(
            allowed=True, note="consented customers with an alternate method"
        ),
        ActionType.DEFER_UNTIL_RECOVERED: _YES,
        ActionType.ESCALATE_HUMAN: MatrixEntry(allowed=True, note="optional"),
        ActionType.NO_ACTION: _YES,
    },
    RootCause.GATEWAY_DEGRADATION.value: {
        ActionType.STEER_METHOD: _NO,
        ActionType.SEND_RECOVERY_LINK: MatrixEntry(
            allowed=True,
            requires_segment_recovered=True,
            note="only after the segment has recovered",
        ),
        ActionType.DEFER_UNTIL_RECOVERED: _YES,
        ActionType.ESCALATE_HUMAN: MatrixEntry(allowed=True, required=True, note="informational"),
        ActionType.NO_ACTION: _YES,
    },
    RootCause.MERCHANT_CONFIG.value: {
        ActionType.STEER_METHOD: _NO,
        ActionType.SEND_RECOVERY_LINK: _NO,
        ActionType.DEFER_UNTIL_RECOVERED: _NO,
        ActionType.ESCALATE_HUMAN: MatrixEntry(allowed=True, required=True),
        ActionType.NO_ACTION: _YES,
    },
    RootCause.CUSTOMER_SIDE.value: {
        ActionType.STEER_METHOD: _NO,
        ActionType.SEND_RECOVERY_LINK: MatrixEntry(
            allowed=True,
            requires_value_threshold=True,
            single_nudge_only=True,
            note="single nudge above the value threshold",
        ),
        ActionType.DEFER_UNTIL_RECOVERED: _NO,
        ActionType.ESCALATE_HUMAN: MatrixEntry(allowed=True, note="optional"),
        ActionType.NO_ACTION: _YES,
    },
    RootCause.UNKNOWN.value: {
        ActionType.STEER_METHOD: _NO,
        ActionType.SEND_RECOVERY_LINK: _NO,
        ActionType.DEFER_UNTIL_RECOVERED: _NO,
        ActionType.ESCALATE_HUMAN: MatrixEntry(allowed=True, required=True),
        ActionType.NO_ACTION: _YES,
    },
}

# ESCALATE_HUMAN and NO_ACTION are always allowed, whatever the cause and whatever the confidence
# (Architecture section 7, policy check 1). Keeping them in the matrix as well means the matrix
# stays a complete description of the table; this set is what the policy engine actually consults
# for the exemption.
ALWAYS_ALLOWED = frozenset({ActionType.ESCALATE_HUMAN, ActionType.NO_ACTION})


def matrix_entry(cause: str, action: ActionType) -> MatrixEntry:
    """The cell for this cause and action. An unknown cause allows nothing but escalation."""
    cells = CAUSE_ACTION_MATRIX.get(cause)
    if cells is None:
        return _YES if action in ALWAYS_ALLOWED else _NO
    return cells.get(action, _NO)


def required_actions(cause: str) -> list[ActionType]:
    """Actions the matrix marks required for a cause, so a plan that omits them is incomplete."""
    cells = CAUSE_ACTION_MATRIX.get(cause, {})
    return [action for action, entry in cells.items() if entry.required]


def validate_params(action: ActionType, params: dict[str, Any]) -> BaseModel:
    """Params validated against the model for this action type.

    An unknown key is rejected because every params model forbids extras, so a model that invents
    an `amount` field fails here rather than reaching the executor.
    """
    return PARAMS_MODEL[action].model_validate(params or {})
