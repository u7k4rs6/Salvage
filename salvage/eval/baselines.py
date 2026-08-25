"""Policies under comparison, and the order set they are all compared over.

docs/02_TECHNICAL_ARCHITECTURE.md section 10:

  Baselines share the executor and the policy engine's consent and quiet-hour rules; they differ
  only in decision logic: B0 does nothing, B1 sends one link immediately to every consented failed
  order, B2 sends retry prompts at 1 hour and 6 hours.

docs/01_PRD.md section 12 says what "only in decision logic" means concretely:

  Baselines respect consent and quiet hours too. They differ from the agent only in what the agent
  is supposed to be good at: cause-aware timing and method steering.

So a baseline turns off exactly two policy checks, the cause-to-action matrix and
defer-while-degraded, and obeys every other check the agent obeys: consent, opt-out, the two
frequency caps, the unpaid-order check, one-open-link, TTL, hard declines, quiet hours, the kill
switch and the circuit breaker. Both skipped checks still emit a gate record naming themselves as
skipped, so a baseline's gate_json is never quietly shorter than the agent's and nobody can read a
missing rule as a passing one.

The eligible order set is the same for every policy, by construction. That is what makes the
headline table a comparison rather than four unrelated numbers, and a test asserts it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PolicyProfile:
    """One arm of the comparison."""

    name: str
    description: str

    # Does this policy diagnose the incident and plan against a cause? Only the agent does.
    diagnoses: bool = False
    # Does the cause-to-action matrix apply? Only meaningful when there is a cause.
    applies_matrix: bool = False
    # Does a send into a still-degraded rail become a deferral? This is cause-aware timing.
    defers_while_degraded: bool = False
    # May this policy set a checkout display hint? This is method steering.
    allows_steer: bool = False
    # Does this policy send recovery links at all?
    sends_links: bool = False
    # For the fixed-schedule baselines: seconds after the order's first failure at which a nudge is
    # attempted. Empty for the agent, whose timing comes from its plan and its gates.
    nudge_offsets: tuple[int, ...] = ()
    # Does the "model" half of the diagnosis just repeat the rules verdict? Only the echo arm.
    # Everything downstream is unchanged: the echo goes through the same reconciliation, the same
    # confidence gate, the same matrix and the same live planner. The arm exists to price the
    # model's diagnosis accuracy in rupees rather than in accuracy points.
    echoes_rules: bool = False

    @property
    def is_agent(self) -> bool:
        return self.diagnoses


AGENT = PolicyProfile(
    name="agent",
    description=(
        "Detect, diagnose, plan against the cause-to-action matrix, gate every action, steer "
        "away from the failing instrument and hold sends until the rail recovers."
    ),
    diagnoses=True,
    applies_matrix=True,
    defers_while_degraded=True,
    allows_steer=True,
    sends_links=True,
)

ECHO = PolicyProfile(
    name="echo",
    description=(
        "The agent with its diagnosis model replaced by a stub that repeats the rules "
        "classifier's verdict at the minimum confidence that counts as agreement. Same "
        "reconciliation, same gate, same matrix, same planner. It exists to answer what the "
        "model's accuracy is worth in money rather than in accuracy points."
    ),
    diagnoses=True,
    applies_matrix=True,
    defers_while_degraded=True,
    allows_steer=True,
    sends_links=True,
    echoes_rules=True,
)

B0 = PolicyProfile(
    name="B0",
    description="Do nothing. Whatever is recovered here is what customers do on their own.",
)

B1 = PolicyProfile(
    name="B1",
    description=(
        "Send one recovery link immediately to every consented failed order, whatever the cause "
        "and whether or not the rail is still broken."
    ),
    sends_links=True,
    nudge_offsets=(0,),
)

B2 = PolicyProfile(
    name="B2",
    description=(
        "Send retry prompts at 1 hour and 6 hours after the failure, regardless of cause."
    ),
    sends_links=True,
    nudge_offsets=(3600, 6 * 3600),
)

POLICIES: dict[str, PolicyProfile] = {
    profile.name: profile for profile in (AGENT, ECHO, B0, B1, B2)
}
# The echo arm is not in the default order. It is a control, reported beside the agent in its own
# right, and putting it in the default sweep order would quietly change every existing command.
DEFAULT_POLICY_ORDER = ("agent", "B0", "B1", "B2")


def get_policy(name: str) -> PolicyProfile:
    try:
        return POLICIES[name]
    except KeyError:
        known = ", ".join(POLICIES)
        raise ValueError(f"unknown policy {name!r}; known: {known}") from None


# ---------------------------------------------------------------------------
# The order set every policy is measured over
# ---------------------------------------------------------------------------

# One row per order whose first payment attempt failed. Computed from v_orders and
# v_payment_attempts, so no ground truth is involved and the set does not depend on which policy
# ran or on whether an incident was detected.
_ELIGIBLE_SQL = """
    WITH first_attempt AS (
        SELECT a.order_id,
               a.id AS attempt_id,
               a.created_at,
               a.status,
               a.error_reason,
               a.method,
               ROW_NUMBER() OVER (PARTITION BY a.order_id ORDER BY a.created_at, a.id) AS rn
        FROM v_payment_attempts a
    )
    SELECT f.order_id, f.created_at AS failed_at, f.error_reason, f.method,
           o.amount, o.customer_id
    FROM first_attempt f
    JOIN v_orders o ON o.id = f.order_id
    WHERE f.rn = 1 AND f.status = 'failed'
      AND f.created_at >= ? AND f.created_at < ?
    ORDER BY f.created_at, f.order_id
"""


@dataclass(frozen=True)
class EligibleOrder:
    order_id: str
    customer_id: str
    amount: int
    failed_at: int
    error_reason: str | None
    method: str


def eligible_orders(conn, *, start: int, end: int) -> list[EligibleOrder]:
    """Every order whose first attempt failed in [start, end).

    Identical for every policy at a given scenario and seed, because it is a property of the
    simulated world and nothing a policy does creates or removes a payment attempt. That is the
    claim `tests/unit/test_comparability.py` checks.
    """
    return [
        EligibleOrder(
            order_id=str(row["order_id"]),
            customer_id=str(row["customer_id"]),
            amount=int(row["amount"]),
            failed_at=int(row["failed_at"]),
            error_reason=row["error_reason"],
            method=str(row["method"]),
        )
        for row in conn.execute(_ELIGIBLE_SQL, (start, end))
    ]


def eligible_order_ids(conn, *, start: int, end: int) -> list[str]:
    return [order.order_id for order in eligible_orders(conn, start=start, end=end)]


# ---------------------------------------------------------------------------
# The at-risk order set
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FaultWindow:
    """One fault's window and the instruments it hit.

    Comes from the simulator's fault schedule, which is ground truth, so only the evaluation
    runner builds these. It is used to define a denominator, never to make a decision: no policy
    code path receives one.
    """

    start: int
    end: int
    selector: dict[str, str]


# The instrument columns a fault selector can name, mapped to the attempt columns they match.
_SELECTOR_COLUMNS = {
    "method": "method",
    "upi_handle": "upi_handle",
    "card_bin": "card_bin",
    "card_issuer": "card_issuer",
    "card_network": "card_network",
    "nb_bank": "nb_bank",
}

_AT_RISK_SQL = """
    WITH first_attempt AS (
        SELECT a.order_id, a.id AS attempt_id, a.created_at, a.status, a.error_reason, a.method,
               a.upi_handle, a.card_bin, a.card_issuer, a.card_network, a.nb_bank,
               ROW_NUMBER() OVER (PARTITION BY a.order_id ORDER BY a.created_at, a.id) AS rn
        FROM v_payment_attempts a
    )
    SELECT f.order_id, f.created_at AS failed_at, f.error_reason, f.method, f.upi_handle,
           f.card_bin, f.card_issuer, f.card_network, f.nb_bank, o.amount, o.customer_id
    FROM first_attempt f
    JOIN v_orders o ON o.id = f.order_id
    WHERE f.rn = 1 AND f.status = 'failed'
    ORDER BY f.created_at, f.order_id
"""


def at_risk_orders(conn, windows: list[FaultWindow]) -> list[EligibleOrder]:
    """Orders the fault actually put at risk.

    An order is at risk when its first payment attempt failed inside a fault window **and** on the
    instrument that fault was breaking. Both halves matter. Without the window, the set is every
    failure in the day, most of which is ordinary background noise no policy is aimed at; without
    the selector, a UPI handle outage would count every card failure in the same ninety minutes as
    something the agent should have saved.

    This is the denominator PRD section 11 means by at-risk revenue, and it is identical across
    policy arms by construction: it is computed from the world's fault schedule and the attempt
    stream, neither of which any policy touches.

    With no faults, as in S0, the set is empty. That is the correct answer and it is the point:
    on a day when nothing broke there is nothing at risk, so a policy that sends a thousand
    messages that day has spent them on nothing.
    """
    if not windows:
        return []
    out: list[EligibleOrder] = []
    for raw in conn.execute(_AT_RISK_SQL):
        row = dict(raw)
        if any(_matches(row, window) for window in windows):
            out.append(
                EligibleOrder(
                    order_id=str(row["order_id"]),
                    customer_id=str(row["customer_id"]),
                    amount=int(row["amount"]),
                    failed_at=int(row["failed_at"]),
                    error_reason=row["error_reason"],
                    method=str(row["method"]),
                )
            )
    return out


def _matches(row: dict[str, Any], window: FaultWindow) -> bool:
    if not (window.start <= int(row["failed_at"]) < window.end):
        return False
    for key, value in window.selector.items():
        column = _SELECTOR_COLUMNS.get(key)
        if column is None:
            return False
        if row.get(column) != value:
            return False
    return True


def at_risk_order_ids(conn, windows: list[FaultWindow]) -> list[str]:
    return [order.order_id for order in at_risk_orders(conn, windows)]


@dataclass
class ProfileCounters:
    """Bookkeeping a runner fills in as it acts, for the decomposition table."""

    steer_opportunities: int = 0
    steer_recoveries: int = 0
    steer_amount: int = 0
    extra: dict[str, Any] = field(default_factory=dict)
