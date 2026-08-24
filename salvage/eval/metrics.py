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
from dataclasses import dataclass


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
