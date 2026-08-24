"""Evaluation metrics.

M2 needs one of them now: root-cause accuracy, reported separately for the rules classifier and
for the LLM-assisted diagnosis. docs/01_PRD.md section 12 requires both, and requires the results
to say so plainly if the model adds nothing.

This module reads simulator ground truth. Architecture section 10 says the evaluation runner is
the only code allowed to do that, and this is part of it. Nothing in salvage/detect,
salvage/diagnose, salvage/decide or salvage/execute may import from here.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from salvage.eval.baselines import eligible_orders

# How a paid order came to be paid. Attribution is first past the post: an order is paid once, and
# whichever route got there first gets the credit. Recorded on the order in `recovery_route`.
ROUTE_LINK = "link"
ROUTE_STEER = "steer"
ROUTE_ORGANIC = "organic"
ROUTES = (ROUTE_LINK, ROUTE_STEER, ROUTE_ORGANIC)


@dataclass
class RunMetrics:
    """One (scenario, seed, policy) run, measured over the shared eligible order set.

    The primary numbers are `recovered_amount` and `recovered_orders`: total revenue and total
    orders recovered by any route at all, including customers who simply came back on their own.
    That is the only quantity that means the same thing for every policy, and it is the only one
    the headline table carries.

    The decomposition underneath says how each policy got there. It is not comparable across
    policies on its own: B0 has no link column by construction, and reading its organic column
    against the agent's link column would be comparing a total to a part. The M2 report made
    exactly that mistake, quoting "16 cases recovered by the agent" beside "106 of 467 organic",
    which are different quantities.
    """

    scenario: str
    seed: int
    policy: str
    variant: str = "peak"

    eligible_orders: int = 0
    eligible_amount: int = 0

    recovered_orders: int = 0
    recovered_amount: int = 0

    by_route_orders: dict[str, int] = field(default_factory=dict)
    by_route_amount: dict[str, int] = field(default_factory=dict)

    # In-fault population: the orders whose first attempt failed inside a fault window. This is
    # the population a recovery agent is aimed at; the rest is ordinary background failure that no
    # policy can do much about and that dilutes every rate it appears in.
    fault_eligible_orders: int = 0
    fault_eligible_amount: int = 0
    fault_recovered_orders: int = 0
    fault_recovered_amount: int = 0

    messages_sent: int = 0
    links_created: int = 0
    opt_outs: int = 0
    escalations: int = 0
    incidents: int = 0
    actions_refused: int = 0
    policy_violations: int = 0
    time_to_detect_minutes: float | None = None
    stream_digest: str = ""

    @property
    def recovery_rate(self) -> float:
        return self.recovered_orders / self.eligible_orders if self.eligible_orders else 0.0

    @property
    def fault_recovery_rate(self) -> float:
        if not self.fault_eligible_orders:
            return 0.0
        return self.fault_recovered_orders / self.fault_eligible_orders

    @property
    def contacts_per_1000_rupees(self) -> float:
        """docs/01_PRD.md section 11: messages sent per 1,000 rupees recovered.

        Zero recovery with messages sent is infinite, not zero, so it is reported as such rather
        than flattered to a small number.
        """
        rupees = self.recovered_amount / 100.0
        if rupees <= 0:
            return float("inf") if self.messages_sent else 0.0
        return self.messages_sent / (rupees / 1000.0)

    def as_dict(self) -> dict[str, Any]:
        data = {k: v for k, v in self.__dict__.items()}
        data["recovery_rate"] = self.recovery_rate
        data["fault_recovery_rate"] = self.fault_recovery_rate
        data["contacts_per_1000_rupees"] = self.contacts_per_1000_rupees
        return data


def measure_run(
    conn,
    *,
    scenario: str,
    seed: int,
    policy: str,
    variant: str,
    window_start: int,
    window_end: int,
    fault_windows: list[tuple[int, int]] | None = None,
) -> RunMetrics:
    """Measure one run over the shared eligible order set.

    Reads v_orders and v_payment_attempts and the recovery tables. No ground truth: fault_windows
    are passed in by the runner, which is the only code allowed to know them.
    """
    fault_windows = fault_windows or []
    orders = eligible_orders(conn, start=window_start, end=window_end)
    metrics = RunMetrics(scenario=scenario, seed=seed, policy=policy, variant=variant)
    metrics.by_route_orders = dict.fromkeys(ROUTES, 0)
    metrics.by_route_amount = dict.fromkeys(ROUTES, 0)

    paid = {
        str(row["id"]): (int(row["paid_at"]) if row["paid_at"] is not None else None)
        for row in conn.execute("SELECT id, paid_at, status FROM v_orders WHERE status = 'paid'")
    }
    routes = {
        str(row["order_id"]): str(row["route"])
        for row in conn.execute(
            "SELECT order_id, route FROM recovery_routes"
        )
    }

    for order in orders:
        metrics.eligible_orders += 1
        metrics.eligible_amount += order.amount
        in_fault = any(start <= order.failed_at < end for start, end in fault_windows)
        if in_fault:
            metrics.fault_eligible_orders += 1
            metrics.fault_eligible_amount += order.amount

        if order.order_id not in paid:
            continue
        metrics.recovered_orders += 1
        metrics.recovered_amount += order.amount
        route = routes.get(order.order_id, ROUTE_ORGANIC)
        metrics.by_route_orders[route] = metrics.by_route_orders.get(route, 0) + 1
        metrics.by_route_amount[route] = metrics.by_route_amount.get(route, 0) + order.amount
        if in_fault:
            metrics.fault_recovered_orders += 1
            metrics.fault_recovered_amount += order.amount

    return metrics


def format_metrics_table(rows: list[RunMetrics], *, title: str = "") -> str:
    """One row per run, with the primary number first and the decomposition after it.

    The primary number is total recovered revenue over the shared eligible order set. The route
    columns underneath are a decomposition of that same number, never an alternative to it: the
    M2 report compared the agent's link count against B0's organic count, which are a part and a
    whole and are not comparable.
    """
    header = (
        f"{'scenario':<9}{'seed':>5}{'policy':>7}{'eligible':>10}{'recovered':>11}"
        f"{'rate':>7}{'revenue (paise)':>17}{'link':>7}{'steer':>7}{'organic':>9}"
        f"{'msgs':>7}{'viol':>6}"
    )
    lines = [line for line in (title, "") if title] + [header, "-" * len(header)]
    for row in rows:
        lines.append(
            f"{row.scenario:<9}{row.seed:>5}{row.policy:>7}{row.eligible_orders:>10}"
            f"{row.recovered_orders:>11}{row.recovery_rate:>7.3f}{row.recovered_amount:>17}"
            f"{row.by_route_orders.get('link', 0):>7}{row.by_route_orders.get('steer', 0):>7}"
            f"{row.by_route_orders.get('organic', 0):>9}{row.messages_sent:>7}"
            f"{row.policy_violations:>6}"
        )
    return "\n".join(lines)


@dataclass(frozen=True)
class DiagnosisOutcome:
    """One incident's diagnosis against the truth for the fault that caused it."""

    scenario: str
    seed: int
    incident_id: str
    segment_key: str
    true_cause: str
    rules_cause: str
    llm_cause: str | None
    reconciled_cause: str | None
    confidence: float | None

    @property
    def rules_correct(self) -> bool:
        return self.rules_cause == self.true_cause

    @property
    def llm_correct(self) -> bool | None:
        if self.llm_cause is None:
            return None
        return self.llm_cause == self.true_cause

    @property
    def reconciled_correct(self) -> bool | None:
        if self.reconciled_cause is None:
            return None
        return self.reconciled_cause == self.true_cause


def true_cause_for(conn, run_id: str, opened_at: int) -> str | None:
    """The true cause of the fault an incident's window overlaps.

    Ground truth. An incident opened outside every fault window has no true cause, which is
    itself informative: it is a false alarm.
    """
    rows = conn.execute(
        "SELECT true_cause, start_ts, end_ts FROM sim_truth_incidents WHERE run_id = ? "
        "ORDER BY start_ts",
        (run_id,),
    ).fetchall()
    for row in rows:
        if row["start_ts"] <= opened_at <= row["end_ts"] + 3600:
            return str(row["true_cause"])
    return None


@dataclass(frozen=True)
class AccuracyRow:
    scenario: str
    incidents: int
    rules_correct: int
    llm_correct: int | None
    reconciled_correct: int | None

    @property
    def rules_accuracy(self) -> float:
        return self.rules_correct / self.incidents if self.incidents else 0.0

    @property
    def llm_accuracy(self) -> float | None:
        if self.llm_correct is None or not self.incidents:
            return None
        return self.llm_correct / self.incidents

    @property
    def reconciled_accuracy(self) -> float | None:
        if self.reconciled_correct is None or not self.incidents:
            return None
        return self.reconciled_correct / self.incidents


def summarise(outcomes: list[DiagnosisOutcome]) -> list[AccuracyRow]:
    grouped: dict[str, list[DiagnosisOutcome]] = defaultdict(list)
    for outcome in outcomes:
        grouped[outcome.scenario].append(outcome)

    rows = []
    for scenario in sorted(grouped):
        group = grouped[scenario]
        has_llm = any(o.llm_cause is not None for o in group)
        rows.append(
            AccuracyRow(
                scenario=scenario,
                incidents=len(group),
                rules_correct=sum(1 for o in group if o.rules_correct),
                llm_correct=sum(1 for o in group if o.llm_correct) if has_llm else None,
                reconciled_correct=(
                    sum(1 for o in group if o.reconciled_correct) if has_llm else None
                ),
            )
        )
    return rows


def format_accuracy_table(rows: list[AccuracyRow], outcomes: list[DiagnosisOutcome]) -> str:
    """Rules-only and LLM-assisted side by side, which is what the ablation is."""
    header = (
        f"{'scenario':<10}{'incidents':>11}{'rules':>9}{'llm':>9}{'reconciled':>13}  true cause"
    )
    lines = [header, "-" * (len(header) + 10)]
    truths = {o.scenario: o.true_cause for o in outcomes if o.true_cause}
    for row in rows:
        llm = "n/a" if row.llm_accuracy is None else f"{row.llm_accuracy:.2f}"
        reconciled = "n/a" if row.reconciled_accuracy is None else f"{row.reconciled_accuracy:.2f}"
        lines.append(
            f"{row.scenario:<10}{row.incidents:>11}{row.rules_accuracy:>9.2f}{llm:>9}"
            f"{reconciled:>13}  {truths.get(row.scenario, '')}"
        )

    total = sum(row.incidents for row in rows)
    if total:
        rules = sum(row.rules_correct for row in rows) / total
        lines.append("")
        lines.append(f"Rules-only accuracy across all scenarios: {rules:.3f}")
        llm_rows = [row for row in rows if row.llm_correct is not None]
        if llm_rows:
            llm_total = sum(row.incidents for row in llm_rows)
            llm = sum(row.llm_correct or 0 for row in llm_rows) / llm_total
            reconciled = sum(row.reconciled_correct or 0 for row in llm_rows) / llm_total
            lines.append(f"LLM-only accuracy across all scenarios:   {llm:.3f}")
            lines.append(f"Reconciled accuracy across all scenarios: {reconciled:.3f}")
            if llm <= rules:
                lines.append(
                    "The model did not beat the rules. docs/01_PRD.md section 12 requires this "
                    "to be reported rather than hidden."
                )

    misses = [o for o in outcomes if not o.rules_correct]
    if misses:
        lines.append("")
        lines.append("Rules misses:")
        for outcome in misses[:20]:
            lines.append(
                f"  {outcome.scenario}/seed {outcome.seed} on {outcome.segment_key}: "
                f"truth {outcome.true_cause}, rules said {outcome.rules_cause}"
            )
        if len(misses) > 20:
            lines.append(f"  ... and {len(misses) - 20} more")
    return "\n".join(lines)


