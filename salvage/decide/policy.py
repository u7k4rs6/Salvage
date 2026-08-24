"""Policy engine.

docs/02_TECHNICAL_ARCHITECTURE.md section 7 and docs/03_SECURITY_AND_ACCESS.md section 6.

  Pure functions over the database state, called before every action, not once per plan:

    1. Matrix check: the action type is allowed for the reconciled cause and confidence is at
       least 0.6 (except ESCALATE_HUMAN and NO_ACTION, always allowed).
    2. Case check: the order is unpaid, no open link exists, the case is not terminal, TTL not
       exceeded, no hard-decline reason on the last attempt.
    3. Customer check: consent true, not opted out, nudges this incident below 2, nudges in the
       last 7 days below 3.
    4. Timing check: not inside quiet hours (else schedule for 09:00 IST); the customer's method
       is not still degraded (else convert to DEFER_UNTIL_RECOVERED).
    5. Global check: kill switch off; circuit breaker for the incident not tripped.

  Each check produces a {rule, passed, detail} record; the full list is stored in
  actions.gate_json and the ledger. A refused action never executes and, when refused for a matrix
  violation, opens an escalation.

Every function here reads state and returns a verdict. Nothing in this module writes, calls
Razorpay, or sends anything. That is what makes the property tests in
tests/property/test_policy_invariants.py able to make claims about all inputs rather than about
the ones somebody thought to try.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from salvage import repo, taxonomy
from salvage.decide.menu import ALWAYS_ALLOWED, ActionType, matrix_entry
from salvage.diagnose.reconcile import ACTION_CONFIDENCE_THRESHOLD
from salvage.sim.clock import IstCalendar

# docs/01_PRD.md section 9. Every bound is here, once.
MAX_NUDGES_PER_INCIDENT = 2
MAX_NUDGES_PER_7_DAYS = 3
QUIET_HOURS_START = 21  # IST
QUIET_HOURS_END = 9  # IST
ORDER_TTL_SECONDS = 72 * 3600
CIRCUIT_FAILURE_RATE = 0.30
CIRCUIT_WINDOW_SECONDS = 10 * 60
CIRCUIT_MIN_ACTIONS = 10
CIRCUIT_MIN_SENDS_BEFORE_PAY_RATE = 50
CIRCUIT_MIN_PAY_RATE = 0.02
SEVEN_DAYS = 7 * 86400

# customer_side's "single nudge above the value threshold" (Architecture section 7). The document
# does not give the number. 1,500 rupees: below it, one message per failed order costs more in
# customer patience than the order is worth, and the value bands in sim/params.yaml put the median
# order just under it. Recorded in docs/BUILD_LOG.md.
VALUE_THRESHOLD_PAISE = 150_000


class Decision(StrEnum):
    ALLOW = "allow"
    REFUSE = "refuse"
    DEFER = "defer"
    QUEUE = "queue"


@dataclass(frozen=True)
class GateResult:
    """One check. The shape Architecture section 7 requires: {rule, passed, detail}."""

    rule: str
    passed: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"rule": self.rule, "passed": self.passed, "detail": self.detail}


@dataclass
class PolicyVerdict:
    decision: Decision
    gates: list[GateResult] = field(default_factory=list)
    # Set when the decision is DEFER or QUEUE.
    scheduled_for: int | None = None
    converted_to: ActionType | None = None

    @property
    def allowed(self) -> bool:
        return self.decision == Decision.ALLOW

    @property
    def first_failure(self) -> GateResult | None:
        return next((gate for gate in self.gates if not gate.passed), None)

    @property
    def refusing_rule(self) -> str | None:
        gate = self.first_failure
        return gate.rule if gate else None

    def gates_json(self) -> list[dict[str, Any]]:
        return [gate.as_dict() for gate in self.gates]


@dataclass(frozen=True)
class ActionContext:
    """Everything a gate needs, read from the database by the caller.

    A frozen snapshot rather than a live connection, so every check is a pure function of its
    inputs and Hypothesis can generate contexts directly.
    """

    action_type: ActionType
    cause: str
    confidence: float
    incident_id: str
    now: int

    # Case and order
    case_id: str | None = None
    order_paid: bool = False
    order_created_at: int = 0
    order_amount: int = 0
    case_state: str | None = None
    case_terminal: bool = False
    open_link_exists: bool = False
    last_attempt_reason: str | None = None

    # Customer
    consent: bool = True
    opted_out: bool = False
    nudges_this_incident: int = 0
    nudges_last_7_days: int = 0

    # Timing
    segment_degraded: bool = False
    segment_recovered: bool = False

    # Global
    kill_switch: bool = False
    circuit_open: bool = False
    circuit_detail: str = ""


# ---------------------------------------------------------------------------
# The five checks
# ---------------------------------------------------------------------------


def check_matrix(context: ActionContext) -> list[GateResult]:
    """1. The action is allowed for the cause, and confidence clears the threshold."""
    action = context.action_type
    if action in ALWAYS_ALLOWED:
        return [
            GateResult(
                "matrix.always_allowed",
                True,
                f"{action.value} is allowed for every cause and at any confidence",
            )
        ]

    entry = matrix_entry(context.cause, action)
    gates = [
        GateResult(
            "matrix.action_allowed_for_cause",
            entry.allowed,
            f"{action.value} is {'allowed' if entry.allowed else 'not allowed'} for "
            f"{context.cause}",
        )
    ]
    if not entry.allowed:
        return gates

    gates.append(
        GateResult(
            "matrix.confidence_threshold",
            context.confidence >= ACTION_CONFIDENCE_THRESHOLD,
            f"confidence {context.confidence:.2f} against threshold {ACTION_CONFIDENCE_THRESHOLD}",
        )
    )
    if entry.requires_segment_recovered:
        gates.append(
            GateResult(
                "matrix.requires_segment_recovered",
                context.segment_recovered,
                f"{action.value} for {context.cause} is allowed only after the segment recovers",
            )
        )
    if entry.requires_value_threshold:
        gates.append(
            GateResult(
                "matrix.value_threshold",
                context.order_amount >= VALUE_THRESHOLD_PAISE,
                f"order amount {context.order_amount} paise against threshold "
                f"{VALUE_THRESHOLD_PAISE}",
            )
        )
    if entry.single_nudge_only:
        gates.append(
            GateResult(
                "matrix.single_nudge_only",
                context.nudges_this_incident == 0,
                f"{context.cause} allows one nudge; {context.nudges_this_incident} already sent",
            )
        )
    return gates


def check_case(context: ActionContext) -> list[GateResult]:
    """2. The order is unpaid, no open link, case not terminal, TTL alive, no hard decline."""
    if context.action_type not in (ActionType.SEND_RECOVERY_LINK, ActionType.DEFER_UNTIL_RECOVERED):
        return []

    ttl_at = context.order_created_at + ORDER_TTL_SECONDS
    gates = [
        GateResult(
            "case.order_unpaid",
            not context.order_paid,
            "order is paid" if context.order_paid else "order is unpaid",
        ),
        GateResult(
            "case.no_open_link",
            not context.open_link_exists,
            "an open payment link already exists for this order"
            if context.open_link_exists
            else "no open link for this order",
        ),
        GateResult(
            "case.not_terminal",
            not context.case_terminal,
            f"case state {context.case_state}",
        ),
        GateResult(
            "case.within_ttl",
            context.now <= ttl_at,
            f"now {context.now} against TTL {ttl_at} (72 hours from order creation)",
        ),
        GateResult(
            "case.no_hard_decline",
            not taxonomy.is_hard_decline(context.last_attempt_reason),
            f"last attempt reason {context.last_attempt_reason}",
        ),
    ]
    return gates


def check_customer(context: ActionContext) -> list[GateResult]:
    """3. Consent, opt-out, and the two frequency caps."""
    if context.action_type not in (ActionType.SEND_RECOVERY_LINK,):
        return []
    return [
        GateResult("customer.consent", context.consent, f"consent={context.consent}"),
        GateResult(
            "customer.not_opted_out",
            not context.opted_out,
            "customer has opted out" if context.opted_out else "customer has not opted out",
        ),
        GateResult(
            "customer.incident_cap",
            context.nudges_this_incident < MAX_NUDGES_PER_INCIDENT,
            f"{context.nudges_this_incident} nudges this incident, cap {MAX_NUDGES_PER_INCIDENT}",
        ),
        GateResult(
            "customer.rolling_7_day_cap",
            context.nudges_last_7_days < MAX_NUDGES_PER_7_DAYS,
            f"{context.nudges_last_7_days} nudges in 7 days, cap {MAX_NUDGES_PER_7_DAYS}",
        ),
    ]


def check_timing(
    context: ActionContext, calendar: IstCalendar | None = None
) -> tuple[list[GateResult], int | None, ActionType | None]:
    """4. Quiet hours and defer-while-cause-active.

    Returns the gates plus, when they do not simply pass, what to do instead: a send due inside
    quiet hours is queued for 09:00 IST rather than refused, and a send into a still-degraded
    method becomes a DEFER_UNTIL_RECOVERED rather than a refusal. Both are conversions, not
    failures, which is why this check returns more than a list.
    """
    if context.action_type not in (ActionType.SEND_RECOVERY_LINK,):
        return [], None, None

    calendar = calendar or IstCalendar()
    gates: list[GateResult] = []
    scheduled_for: int | None = None
    converted_to: ActionType | None = None

    if context.segment_degraded:
        gates.append(
            GateResult(
                "timing.method_not_still_degraded",
                False,
                "the customer's method is still degraded, converting to DEFER_UNTIL_RECOVERED",
            )
        )
        converted_to = ActionType.DEFER_UNTIL_RECOVERED
        return gates, None, converted_to

    gates.append(
        GateResult("timing.method_not_still_degraded", True, "the customer's method has recovered")
    )

    in_quiet = calendar.is_quiet_hours(context.now, QUIET_HOURS_START, QUIET_HOURS_END)
    gates.append(
        GateResult(
            "timing.not_quiet_hours",
            not in_quiet,
            f"IST hour {calendar.hour_of_day(context.now)}, quiet hours "
            f"{QUIET_HOURS_START}:00 to {QUIET_HOURS_END}:00",
        )
    )
    if in_quiet:
        scheduled_for = next_quiet_hours_end(context.now, calendar)
    return gates, scheduled_for, converted_to


def next_quiet_hours_end(now: int, calendar: IstCalendar | None = None) -> int:
    """The next 09:00 IST at or after `now`.

    docs/01_PRD.md section 9: sends due in quiet hours are queued for 09:00, not dropped.
    """
    calendar = calendar or IstCalendar()
    day_start = calendar.start_of_day(now)
    target = day_start + QUIET_HOURS_END * 3600
    if target <= now:
        target += 86400
    return target


def check_global(context: ActionContext) -> list[GateResult]:
    """5. Kill switch and circuit breaker.

    Applies to every action type including escalation, because the kill switch is about outbound
    effects and an escalation has none. ESCALATE_HUMAN and NO_ACTION are exempt: the kill switch
    stops outbound actions, and detection, diagnosis and the escalation queue keep working
    (docs/03_SECURITY_AND_ACCESS.md section 6).
    """
    if context.action_type in ALWAYS_ALLOWED:
        return [
            GateResult(
                "global.exempt",
                True,
                f"{context.action_type.value} makes no outbound call",
            )
        ]
    return [
        GateResult(
            "global.kill_switch_off",
            not context.kill_switch,
            "SALVAGE_KILL_SWITCH is set, all outbound actions suspended"
            if context.kill_switch
            else "kill switch off",
        ),
        GateResult(
            "global.circuit_breaker_closed",
            not context.circuit_open,
            context.circuit_detail or "circuit breaker closed",
        ),
    ]


def evaluate(context: ActionContext, calendar: IstCalendar | None = None) -> PolicyVerdict:
    """All five groups, in order, every time, for one action.

    Every gate in a group runs even after one fails, so `gate_json` records the whole picture
    rather than stopping at the first problem. The groups short-circuit, because a matrix refusal
    makes the customer checks meaningless.
    """
    gates: list[GateResult] = []

    matrix = check_matrix(context)
    gates.extend(matrix)
    if any(not gate.passed for gate in matrix):
        return PolicyVerdict(Decision.REFUSE, gates)

    case = check_case(context)
    gates.extend(case)
    if any(not gate.passed for gate in case):
        return PolicyVerdict(Decision.REFUSE, gates)

    customer = check_customer(context)
    gates.extend(customer)
    if any(not gate.passed for gate in customer):
        return PolicyVerdict(Decision.REFUSE, gates)

    timing, scheduled_for, converted_to = check_timing(context, calendar)
    gates.extend(timing)
    if converted_to is not None:
        return PolicyVerdict(Decision.DEFER, gates, converted_to=converted_to)

    global_gates = check_global(context)
    gates.extend(global_gates)
    if any(not gate.passed for gate in global_gates):
        return PolicyVerdict(Decision.REFUSE, gates)

    if scheduled_for is not None:
        return PolicyVerdict(Decision.QUEUE, gates, scheduled_for=scheduled_for)

    return PolicyVerdict(Decision.ALLOW, gates)


def refused_for_matrix(verdict: PolicyVerdict) -> bool:
    """Whether the refusal was a matrix violation, which opens an escalation."""
    gate = verdict.first_failure
    return bool(gate and gate.rule.startswith("matrix."))


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CircuitState:
    open: bool
    detail: str


def circuit_state(conn, incident_id: str, now: int) -> CircuitState:
    """docs/01_PRD.md section 9.

    Trips when outbound actions fail above 30 percent in a rolling 10 minutes with at least 10
    actions, or when fewer than 2 percent of links are paid after 50 sends within the incident.
    """
    row = conn.execute(
        "SELECT COUNT(*) AS total, SUM(status = 'failed') AS failed FROM actions "
        "WHERE incident_id = ? AND executed_at >= ? AND status IN ('executed', 'failed')",
        (incident_id, now - CIRCUIT_WINDOW_SECONDS),
    ).fetchone()
    total = int(row["total"] or 0)
    failed = int(row["failed"] or 0)
    if total >= CIRCUIT_MIN_ACTIONS and total and failed / total > CIRCUIT_FAILURE_RATE:
        return CircuitState(
            True,
            f"{failed}/{total} outbound actions failed in the last 10 minutes, above "
            f"{CIRCUIT_FAILURE_RATE:.0%}",
        )

    sends = conn.execute(
        "SELECT COUNT(*) AS n FROM customer_comms WHERE incident_id = ?", (incident_id,)
    ).fetchone()["n"]
    if sends >= CIRCUIT_MIN_SENDS_BEFORE_PAY_RATE:
        paid = conn.execute(
            "SELECT COUNT(*) AS n FROM recovery_cases WHERE incident_id = ? AND outcome = "
            "'RECOVERED'",
            (incident_id,),
        ).fetchone()["n"]
        if paid / sends < CIRCUIT_MIN_PAY_RATE:
            return CircuitState(
                True,
                f"{paid} paid out of {sends} sends, below {CIRCUIT_MIN_PAY_RATE:.0%}",
            )
    return CircuitState(False, "circuit breaker closed")


# ---------------------------------------------------------------------------
# Building a context from the database
# ---------------------------------------------------------------------------


def build_context(
    conn,
    *,
    action_type: ActionType,
    incident: dict[str, Any],
    now: int,
    case: dict[str, Any] | None = None,
    segment_degraded: bool = False,
    segment_recovered: bool = False,
    kill_switch: bool = False,
) -> ActionContext:
    """Read the state one action needs. Called before every action, never cached across actions.

    Architecture section 7: the policy engine "re-reads state (including a fresh Razorpay order
    fetch for real orders) so a customer who paid in the meantime is never nudged". The Razorpay
    fetch lives in the executor, which passes the result in as order_paid.
    """
    cause = str(incident.get("root_cause") or "unknown")
    confidence = float(incident.get("confidence") or 0.0)
    circuit = circuit_state(conn, str(incident["id"]), now)

    if case is None:
        return ActionContext(
            action_type=action_type,
            cause=cause,
            confidence=confidence,
            incident_id=str(incident["id"]),
            now=now,
            segment_degraded=segment_degraded,
            segment_recovered=segment_recovered,
            kill_switch=kill_switch,
            circuit_open=circuit.open,
            circuit_detail=circuit.detail,
        )

    order = repo.get_order(conn, str(case["order_id"])) or {}
    customer = repo.get_customer(conn, str(case["customer_id"])) or {}
    last_attempt = conn.execute(
        "SELECT error_reason FROM v_payment_attempts WHERE order_id = ? "
        "ORDER BY created_at DESC, id DESC LIMIT 1",
        (case["order_id"],),
    ).fetchone()

    nudges_incident = conn.execute(
        "SELECT COUNT(*) AS n FROM customer_comms WHERE customer_id = ? AND incident_id = ?",
        (case["customer_id"], incident["id"]),
    ).fetchone()["n"]
    nudges_7d = repo.comms_count_for_customer(conn, str(case["customer_id"]), now - SEVEN_DAYS)

    return ActionContext(
        action_type=action_type,
        cause=cause,
        confidence=confidence,
        incident_id=str(incident["id"]),
        now=now,
        case_id=str(case["id"]),
        order_paid=str(order.get("status")) == "paid",
        order_created_at=int(order.get("created_at") or 0),
        order_amount=int(order.get("amount") or 0),
        case_state=str(case.get("state")),
        case_terminal=bool(case.get("outcome")),
        open_link_exists=bool(case.get("link_id")) and not case.get("outcome"),
        last_attempt_reason=(last_attempt["error_reason"] if last_attempt else None),
        consent=bool(customer.get("consent")),
        opted_out=customer.get("opted_out_at") is not None,
        nudges_this_incident=int(nudges_incident),
        nudges_last_7_days=int(nudges_7d),
        segment_degraded=segment_degraded,
        segment_recovered=segment_recovered,
        kill_switch=kill_switch,
        circuit_open=circuit.open,
        circuit_detail=circuit.detail,
    )
