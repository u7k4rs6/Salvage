"""Baselines.

docs/01_PRD.md section 11 names three: B0 does nothing, B1 sends one link immediately to every
consented failed order, B2 sends retry prompts at 1 hour and 6 hours. B1 and B2 need the executor
and land with the evaluation runner in M3.

B0 is measurable now, and it has to be, because it is the floor every other number is compared
against. B0's recovery is exactly the organic behaviour of the response model: a customer whose
payment failed comes back on their own, tries the same instrument again, and either the rail is
working by then or it is not. If B0 recovers nothing, the comparison in docs/RESULTS.md is
meaningless, so this module exists to prove it does not.

Nothing here reads ground truth. It reads v_orders and v_payment_attempts, the same views the
agent uses, so the measurement is over what actually happened rather than over what was intended.
"""

from __future__ import annotations

from dataclasses import dataclass

# One row per (scenario, seed). Attempt counts are over the whole run; the fault-window columns
# cover only orders whose first attempt failed inside a fault window, which is the population the
# agent is supposed to be good at.
_FIRST_ATTEMPT_SQL = """
    WITH first_attempt AS (
        SELECT a.order_id,
               a.id AS attempt_id,
               a.created_at,
               a.status,
               a.error_reason,
               ROW_NUMBER() OVER (PARTITION BY a.order_id ORDER BY a.created_at, a.id) AS rn
        FROM v_payment_attempts a
    )
    SELECT f.order_id, f.created_at, f.status, o.status AS order_status, o.amount
    FROM first_attempt f
    JOIN v_orders o ON o.id = f.order_id
    WHERE f.rn = 1
"""


@dataclass(frozen=True)
class OrganicRecovery:
    scenario: str
    seed: int
    variant: str
    orders: int
    failed_orders: int
    recovered_orders: int
    failed_amount: int
    recovered_amount: int
    fault_failed_orders: int
    fault_recovered_orders: int

    @property
    def recovery_rate(self) -> float:
        return self.recovered_orders / self.failed_orders if self.failed_orders else 0.0

    @property
    def amount_recovery_rate(self) -> float:
        return self.recovered_amount / self.failed_amount if self.failed_amount else 0.0

    @property
    def fault_recovery_rate(self) -> float:
        if not self.fault_failed_orders:
            return 0.0
        return self.fault_recovered_orders / self.fault_failed_orders


def measure_organic_recovery(
    conn,
    *,
    scenario: str,
    seed: int,
    variant: str = "peak",
    fault_windows: list[tuple[int, int]] | None = None,
) -> OrganicRecovery:
    """B0's outcome for one run: how many failed orders got paid with nobody doing anything.

    fault_windows are the (start, end) sim seconds of the run's faults. They come from the sim
    result, not from the ground-truth tables, so this stays usable outside the evaluation runner.
    """
    fault_windows = fault_windows or []
    orders = failed = recovered = 0
    failed_amount = recovered_amount = 0
    fault_failed = fault_recovered = 0

    for row in conn.execute(_FIRST_ATTEMPT_SQL):
        orders += 1
        if row["status"] != "failed":
            continue
        failed += 1
        failed_amount += int(row["amount"])
        in_fault = any(start <= row["created_at"] < end for start, end in fault_windows)
        if in_fault:
            fault_failed += 1
        if row["order_status"] == "paid":
            recovered += 1
            recovered_amount += int(row["amount"])
            if in_fault:
                fault_recovered += 1

    return OrganicRecovery(
        scenario=scenario,
        seed=seed,
        variant=variant,
        orders=orders,
        failed_orders=failed,
        recovered_orders=recovered,
        failed_amount=failed_amount,
        recovered_amount=recovered_amount,
        fault_failed_orders=fault_failed,
        fault_recovered_orders=fault_recovered,
    )


def format_organic_table(rows: list[OrganicRecovery]) -> str:
    """The organic-only recovery table.

    Two recovery columns on purpose. The first is over every failed order in the run, which is
    mostly ordinary background failure. The second is over the orders that failed inside the fault
    window, which is the population a recovery agent is aimed at and the one that moves when the
    agent is good.
    """
    header = (
        f"{'scenario':<10}{'seed':>5}{'failed':>9}{'recovered':>11}{'rate':>8}"
        f"{'fault failed':>14}{'fault recovered':>17}{'fault rate':>12}"
    )
    lines = [header, "-" * len(header)]
    for row in rows:
        lines.append(
            f"{row.scenario:<10}{row.seed:>5}{row.failed_orders:>9}{row.recovered_orders:>11}"
            f"{row.recovery_rate:>8.3f}{row.fault_failed_orders:>14}"
            f"{row.fault_recovered_orders:>17}{row.fault_recovery_rate:>12.3f}"
        )

    lines.append("")
    by_scenario: dict[str, list[OrganicRecovery]] = {}
    for row in rows:
        by_scenario.setdefault(row.scenario, []).append(row)
    lines.append("Means across seeds:")
    for scenario in sorted(by_scenario):
        group = by_scenario[scenario]
        overall = sum(r.recovery_rate for r in group) / len(group)
        in_fault = sum(r.fault_recovery_rate for r in group) / len(group)
        fault_failed = sum(r.fault_failed_orders for r in group) / len(group)
        lines.append(
            f"  {scenario}: organic recovery {overall:.3f} overall, {in_fault:.3f} inside the "
            f"fault window ({fault_failed:.0f} failed orders per run there)"
        )
    zero = [scenario for scenario in sorted(by_scenario)
            if all(r.recovered_orders == 0 for r in by_scenario[scenario])]
    if zero:
        lines.append("")
        lines.append(
            "WARNING: organic recovery is zero for " + ", ".join(zero) +
            ". B0 recovers nothing there, so any comparison against it is meaningless."
        )
    return "\n".join(lines)
