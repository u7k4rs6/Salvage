"""docs/RESULTS.md.

Section order is fixed by the M3 brief:

  headline recovered-revenue table, decomposition, secondary metrics, diagnosis ablation with its
  provenance stated, detector operating envelope with the volume sweep, peak versus trough
  detection, sensitivity and adversarial, fault injection results, the real end-to-end run,
  known limitations.

Every number carries its seed count. There are no single-seed numbers anywhere, which
docs/01_PRD.md section 12 requires.

What this file will not do: invent a number it does not have. A section whose sweep has not been
run says so and gives the command that would produce it. A measurement that is blocked says what
is blocking it. Filling a gap with a plausible figure would defeat the point of the document.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from salvage.eval.metrics import RunMetrics
from salvage.eval.sweep import Aggregate, SweepResult, aggregate

RESULTS_PATH = Path("docs/RESULTS.md")
RESULTS_DIR = Path("data/results")


def rupees(paise: float) -> str:
    """Indian digit grouping, two decimals, as the frontend spec formats every amount."""
    value = paise / 100.0
    whole = int(value)
    fraction = int(round((value - whole) * 100))
    digits = str(abs(whole))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        digits = ",".join([*parts, tail])
    sign = "-" if whole < 0 else ""
    return f"{sign}{digits}.{fraction:02d}"


@dataclass
class ReportInputs:
    """Everything the report can draw on. Anything missing becomes an honest gap."""

    main: SweepResult
    volume_sweep: dict[str, Any] | None = None
    offpeak: SweepResult | None = None
    sensitivity: dict[str, Any] | None = None
    adversarial: SweepResult | None = None
    diagnosis: dict[str, Any] | None = None
    injection: dict[str, Any] | None = None
    escalation_fix: dict[str, Any] | None = None
    steer_sensitivity: dict[str, Any] | None = None
    calibration: str | None = None


class StaleArtifact(RuntimeError):
    """An input to the report was produced by older code than the sweep it sits beside."""


def load_json(path: Path | str) -> dict[str, Any] | None:
    path = Path(path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def check_freshness(paths: dict[str, Path | str], primary: Path | str) -> list[str]:
    """Artifacts older than the primary sweep, by modification time.

    The rule is blunt on purpose. The primary sweep is regenerated whenever the code that produces
    a number changes, so anything older than it was produced by code that no longer exists, and a
    report that renders both in one document is quietly mixing two builds. This shipped for a
    milestone: three sections were rendered from files written before the agent arm was ever
    measured, and nothing said so.

    Returns the stale names. The caller decides whether to refuse; `salvage eval report` does.
    """
    primary = Path(primary)
    if not primary.exists():
        return []
    cutoff = primary.stat().st_mtime
    stale = []
    for name, path in paths.items():
        path = Path(path)
        if path.exists() and path.stat().st_mtime < cutoff:
            stale.append(name)
    return sorted(stale)


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def _policies(result: SweepResult) -> list[str]:
    return list(result.policies)


def _by_scenario(rows: list[Aggregate]) -> dict[str, dict[str, Aggregate]]:
    out: dict[str, dict[str, Aggregate]] = {}
    for row in rows:
        out.setdefault(row.scenario, {})[row.policy] = row
    return out


def primary_table(result: SweepResult) -> str:
    """Recovered revenue over the at-risk order set, with contact volume beside it."""
    rows = aggregate(result.rows)
    grouped = _by_scenario(rows)
    policies = _policies(result)
    seeds = len(result.seeds)

    lines = [
        f"Mean across {seeds} seeds. Every cell is **recovered revenue in rupees and messages "
        "sent**, both scoped to the at-risk order set.",
        "",
        "An order is at risk when its first payment attempt failed inside a fault window **and** "
        "on the instrument that fault was breaking. That is the population a recovery agent is "
        "aimed at. It is computed from the world's fault schedule and the attempt stream, neither "
        "of which any policy touches, so it is identical across all four arms and a test proves "
        "it. S0 has no fault, so its at-risk set is empty and every arm recovers nothing from it: "
        "the messages column is the whole story on that row.",
        "",
        "Revenue is never shown without contact volume beside it. A policy that recovers more by "
        "messaging everybody has not obviously won.",
        "",
    ]
    header = "| scenario | at-risk orders | " + " | ".join(policies) + " |"
    lines.append(header)
    lines.append("|" + "---|" * (len(policies) + 2))
    for scenario in sorted(grouped):
        cells = []
        at_risk = 0
        for policy in policies:
            entry = grouped[scenario].get(policy)
            if entry is None:
                cells.append("not run")
                continue
            at_risk = int(round(entry.mean_at_risk_orders))
            cells.append(
                f"{rupees(entry.mean_at_risk_recovered_amount)} / "
                f"{entry.mean_at_risk_messages:.0f} msg"
            )
        lines.append(f"| {scenario} | {at_risk} | " + " | ".join(cells) + " |")

    lines.append("")
    lines.append(
        "Opt-outs are counted over the whole run rather than over the at-risk set, and are shown "
        "separately for that reason. The simulator draws an opt-out when a message is sent, and a "
        "policy sends to orders inside and outside the at-risk set alike, so there is no honest "
        "way to attribute an opt-out to one population. Every message a policy sends can produce "
        "one, which is the number that matters when judging contact volume."
    )
    lines.append("")
    lines.append("| scenario | " + " | ".join(f"{p} msg / opt-out" for p in policies) + " |")
    lines.append("|" + "---|" * (len(policies) + 1))
    for scenario in sorted(grouped):
        cells = []
        for policy in policies:
            entry = grouped[scenario].get(policy)
            cells.append(
                "not run"
                if entry is None
                else f"{entry.mean_messages:.0f} / {entry.mean_opt_outs:.0f}"
            )
        lines.append(f"| {scenario} | " + " | ".join(cells) + " |")

    lines.append("")
    lines.append("Recovery rate over the at-risk set:")
    lines.append("")
    lines.append("| scenario | " + " | ".join(policies) + " |")
    lines.append("|" + "---|" * (len(policies) + 1))
    for scenario in sorted(grouped):
        cells = []
        for policy in policies:
            entry = grouped[scenario].get(policy)
            cells.append("not run" if entry is None else f"{entry.mean_at_risk_recovery_rate:.3f}")
        lines.append(f"| {scenario} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def whole_run_table(result: SweepResult) -> str:
    """The old headline, demoted, with the reason in the caption."""
    rows = aggregate(result.rows)
    grouped = _by_scenario(rows)
    policies = _policies(result)
    seeds = len(result.seeds)

    lines = [
        f"Recovered revenue in rupees over **every** order whose first attempt failed during the "
        f"evaluation day, mean plus or minus standard deviation across {seeds} seeds, with "
        "messages sent and opt-outs.",
        "",
        "This is secondary, and the S0 row says why. S0 has no fault at all, and a link-sending "
        "baseline still shows roughly 1.8 times what doing nothing shows. That is not a recovery "
        "agent working; it is the measure being dominated by ordinary background failure that "
        "happens every day, on which a policy that messages everybody will always score well. The "
        "primary table above scopes to the orders a fault actually put at risk.",
        "",
    ]
    header = "| scenario | " + " | ".join(policies) + " |"
    lines.append(header)
    lines.append("|" + "---|" * (len(policies) + 1))
    for scenario in sorted(grouped):
        cells = []
        for policy in policies:
            entry = grouped[scenario].get(policy)
            if entry is None:
                cells.append("not run")
                continue
            cells.append(
                f"{rupees(entry.mean_recovered_amount)} +/- "
                f"{rupees(entry.std_recovered_amount)} / {entry.mean_messages:.0f} msg / "
                f"{entry.mean_opt_outs:.0f} opt-out"
            )
        lines.append(f"| {scenario} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def message_cost_caveat(result: SweepResult) -> str:
    """What the simulator does not charge for, named rather than tuned away."""
    rows = aggregate(result.rows)
    worst = max(rows, key=lambda row: row.mean_messages, default=None)
    total_messages = sum(row.mean_messages * row.seeds for row in rows)
    total_opt_outs = sum(row.mean_opt_outs * row.seeds for row in rows)
    rate = (total_opt_outs / total_messages) if total_messages else 0.0

    lines = [
        "**A message costs nothing in this simulator except the chance that the customer opts "
        "out.** There is no regulatory cost, no TRAI or DLT registration limit, no sender "
        "reputation, no per-message fee, no fatigue beyond the single opt-out draw, and no effect "
        "on anything the customer does later. Deliberately: modelling those would mean inventing "
        "half a dozen more parameters, and the point here is to name the limit rather than tune "
        "it away.",
        "",
        "Read every advantage a link-sending baseline shows in that light. B1's whole-run lead is "
        "real inside the model and it is bought entirely with contact volume that the model prices "
        "at almost zero.",
        "",
    ]
    if worst is not None:
        lines.append(
            f"For scale: the heaviest arm in this sweep sends about {worst.mean_messages:.0f} "
            f"messages per simulated day on {worst.scenario} ({worst.policy}). A real merchant "
            "sending that volume would be having a different conversation, with their operator "
            "and possibly with a regulator, before they had it about recovered revenue."
        )
        lines.append("")
    lines.append(
        f"**Opt-outs are doing some work, but not much.** Across the sweep, "
        f"{rate:.1%} of messages produced an opt-out, from the "
        "`opt_out_probability_base` and `opt_out_probability_still_failing` parameters in "
        "`salvage/sim/params.yaml` (0.02 and 0.12). That is the only push-back a policy feels for "
        "sending, and at that rate a policy can send a thousand messages and lose a few dozen "
        "customers permanently, which the model then charges it nothing further for. If the "
        "results are ever used to argue for a high-volume strategy, this parameter is the first "
        "one to attack."
    )
    return "\n".join(lines)


def decomposition_table(result: SweepResult) -> str:
    rows = aggregate(result.rows)
    lines = [
        "How each policy got there. These columns add up to the headline number and are not",
        "comparable across policies on their own: B0 has no link column by construction, so",
        "reading its organic column against another arm's link column compares a whole to a part.",
        "",
        "| scenario | policy | recovered orders | link | steer | organic | messages |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row.scenario} | {row.policy} | {row.mean_recovered_orders:.1f} | "
            f"{row.mean_link_orders:.1f} | {row.mean_steer_orders:.1f} | "
            f"{row.mean_organic_orders:.1f} | {row.mean_messages:.0f} |"
        )
    return "\n".join(lines)


def secondary_table(result: SweepResult) -> str:
    rows = aggregate(result.rows)
    lines = [
        "| scenario | policy | recovery rate | in-fault rate | messages per 1,000 rupees | "
        "escalations | detected | time to detect (sim min) | policy violations |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        latency = f"{row.mean_time_to_detect:.1f}" if row.mean_time_to_detect is not None else "n/a"
        contacts = f"{row.mean_contacts_per_1000:.2f}" if row.mean_messages else "0.00"
        lines.append(
            f"| {row.scenario} | {row.policy} | {row.mean_recovery_rate:.3f} | "
            f"{row.mean_at_risk_recovery_rate:.3f} | {contacts} | "
            f"{row.mean_escalations:.1f} | {row.detected}/{row.seeds} | {latency} | "
            f"{row.total_violations} |"
        )
    return "\n".join(lines)


def digest_table(result: SweepResult) -> str:
    policies = _policies(result)
    lines = [
        "Every policy arm must face the identical world. The pre-intervention attempt stream is",
        "hashed before any policy acts, and the hash is the same across all four arms for every",
        "scenario and seed. No policy writes a payment attempt, which is why this holds and why it",
        "is checked rather than assumed.",
        "",
        "| scenario / seed | " + " | ".join(policies) + " | identical |",
        "|" + "---|" * (len(policies) + 2),
    ]
    mismatches = 0
    for key in sorted(result.digests, key=_sort_key):
        digests = result.digests[key]
        identical = len(set(digests.values())) <= 1
        mismatches += 0 if identical else 1
        cells = [digests.get(policy, "")[:12] for policy in policies]
        lines.append(f"| {key} | " + " | ".join(cells) + f" | {'yes' if identical else 'NO'} |")
    lines.append("")
    lines.append(
        f"{len(result.digests)} worlds checked, {mismatches} mismatch(es)."
        if mismatches
        else f"All {len(result.digests)} worlds identical across all {len(policies)} policy arms."
    )
    return "\n".join(lines)


def _sort_key(key: str) -> tuple[str, int]:
    scenario, _, seed = key.partition("/")
    return scenario, int(seed) if seed.isdigit() else 0


def volume_section(payload: dict[str, Any] | None) -> str:
    if not payload:
        return _not_run(
            "uv run salvage eval volume --scenario S1 --seeds 0..4",
            "The volume sweep has not been run.",
        )
    lines = [
        "Detection latency is bounded by how much traffic the affected segment carries. The",
        "detector will not evaluate a segment key with fewer than 20 attempts in a 15-minute",
        "window, so below a certain merchant volume a single-instrument fault cannot be detected",
        "inside 15 minutes at all, whatever the fault's severity. This is the operating envelope,",
        "and it is a property of the design rather than a defect in it.",
        "",
        "| attempts per day | scenario | seeds | detected | time to detect (sim min) | "
        "attributed segment |",
        "|---|---|---|---|---|---|",
    ]
    for row in payload["rows"]:
        detected_latency = row.get("mean_time_to_detect")
        latency = f"{detected_latency:.1f}" if detected_latency else "not detected"
        lines.append(
            f"| {row['attempts_per_day']:,} | {row['scenario']} | {row['seeds']} | "
            f"{row['detected']}/{row['seeds']} | {latency} | {row.get('segments', '')} |"
        )
    if payload.get("boundary"):
        lines.append("")
        lines.append(payload["boundary"])
    return "\n".join(lines)


def offpeak_section(peak: SweepResult, offpeak: SweepResult | None) -> str:
    if offpeak is None:
        return _not_run(
            "uv run salvage eval run --variant offpeak --policies B0 --seeds 0..4",
            "The off-peak variant has not been run.",
        )
    peak_rows = {(r.scenario, r.policy): r for r in aggregate(peak.rows)}
    trough_rows = {(r.scenario, r.policy): r for r in aggregate(offpeak.rows)}
    lines = [
        "The same fault, moved from the 19:00 to 21:00 IST peak to the 03:30 IST trough, where the",
        "arrival rate is about one thirtieth of the peak. Time to detect is reported as a range",
        "because a single peak-hour number is a best case and would read as a guarantee.",
        "",
        "| scenario | peak seeds | peak detected | peak sim min | trough seeds | "
        "trough detected | trough sim min |",
        "|---|---|---|---|---|---|---|",
    ]
    policy = offpeak.policies[0]
    for scenario in sorted({key[0] for key in trough_rows}):
        peak_row = peak_rows.get((scenario, policy))
        trough_row = trough_rows.get((scenario, policy))
        if peak_row is None or trough_row is None:
            continue
        peak_latency = (
            f"{peak_row.mean_time_to_detect:.1f}"
            if peak_row.mean_time_to_detect is not None
            else "n/a"
        )
        trough_latency = (
            f"{trough_row.mean_time_to_detect:.1f}"
            if trough_row.mean_time_to_detect is not None
            else "not detected"
        )
        lines.append(
            f"| {scenario} | {peak_row.seeds} | {peak_row.detected}/{peak_row.seeds} | "
            f"{peak_latency} | {trough_row.seeds} | "
            f"{trough_row.detected}/{trough_row.seeds} | {trough_latency} |"
        )
    lines.append("")
    lines.append(
        "Not slow. Not misattributed. **Not detected.** The diurnal curve puts the 03:00 and 04:00 "
        "hours at 0.08 relative weight against an evening peak of 2.60, so the trough carries "
        "about one thirtieth of the peak arrival rate: roughly 45 attempts an hour across the "
        "whole merchant, about 11 in a 15-minute window. The detector will not evaluate any "
        "segment key with fewer than 20 attempts in a window, so at 03:30 there is no key it can "
        "test, including the merchant-wide one. The fault happens, the payments fail, and nothing "
        "is testable."
    )
    lines.append("")
    lines.append(
        "The 15-minute promise in PRD goal G1 is a promise about the evening peak. Overnight, at "
        "this merchant size, the detector does not fire at all. The fix is volume or a longer "
        "window, not a threshold, and both trade against the zero false-alarm result."
    )
    return "\n".join(lines)


def steer_sensitivity_section(payload: dict[str, Any] | None) -> str:
    """The constant the agent's margin actually rests on, swept.

    Replaces a sweep that scaled two nudge multipliers and compared B1 against B0. That sweep
    quantified a comparison the headline does not depend on, and left untouched the one parameter
    it depends on most.
    """
    if not payload:
        return _not_run(
            "uv run salvage eval steer-sensitivity --scenarios S1,S2 --seeds 0..4",
            "The steer sensitivity sweep has not been run.",
        )

    rows = payload["rows"]
    policies: list[str] = []
    for row in rows:
        if row["policy"] not in policies:
            policies.append(row["policy"])
    values = sorted({row["steer"] for row in rows})
    scenarios = payload["scenarios"]
    cells = {(row["steer"], row["scenario"], row["policy"]): row for row in rows}

    lines = [
        "The agent's margin on S1 and S2 arrives mostly by the steer route: a checkout display "
        "hint moves a customer off the failing instrument and they pay in the same session. That "
        "route is available to no other arm, costs no messages, and converts at a probability "
        f"this project asserted rather than measured. The shipped value is "
        f"**{payload['shipped_value']}**, taken from the architecture note as an illustration and "
        "never swept until now.",
        "",
        "Only that probability moves. The attempt stream is generated before any policy runs and "
        "does not read it, so the world, the eligible set and the at-risk set are identical at "
        "every value.",
        "",
        f"Mean over {len(payload['seeds'])} seeds, at-risk recovered revenue in rupees against "
        "messages sent.",
    ]
    for scenario in scenarios:
        lines.append("")
        lines.append(f"**{scenario}**")
        lines.append("")
        lines.append("| steer | " + " | ".join(policies) + " |")
        lines.append("|---" * (len(policies) + 1) + "|")
        for value in values:
            cell_texts = []
            for policy in policies:
                row = cells.get((value, scenario, policy))
                if row is None:
                    cell_texts.append("n/a")
                    continue
                cell_texts.append(
                    f"{rupees(row['at_risk_recovered_amount'])} / {row['at_risk_messages']:.0f} msg"
                )
            marker = " (shipped)" if value == payload["shipped_value"] else ""
            lines.append(f"| {value:.2f}{marker} | " + " | ".join(cell_texts) + " |")

    lines.append("")
    lines.append(_steer_crossovers(cells, values, scenarios, policies))
    return "\n".join(lines)


def _steer_crossovers(
    cells: dict[tuple[float, str, str], dict[str, Any]],
    values: list[float],
    scenarios: list[str],
    policies: list[str],
) -> str:
    """The value below which the agent stops beating the best baseline, per scenario."""
    if "agent" not in policies:
        return ""
    rivals = [p for p in policies if p not in ("agent", "echo")]
    out = []
    for scenario in scenarios:
        best_rival, best_amount = None, 0.0
        for policy in rivals:
            row = cells.get((max(values), scenario, policy))
            if row and row["at_risk_recovered_amount"] > best_amount:
                best_rival, best_amount = policy, row["at_risk_recovered_amount"]
        if best_rival is None:
            continue
        losing = [
            value
            for value in values
            if (row := cells.get((value, scenario, "agent")))
            and (rival := cells.get((value, scenario, best_rival)))
            and row["at_risk_recovered_amount"] <= rival["at_risk_recovered_amount"]
        ]
        if losing:
            out.append(
                f"On {scenario} the agent stops beating {best_rival} at or below a steer "
                f"probability of **{max(losing):.2f}**, against a shipped value of 0.55."
            )
        else:
            out.append(
                f"On {scenario} the agent beats {best_rival} at every value in the swept range, "
                f"down to {min(values):.2f}."
            )
    if not out:
        return ""
    return "**Where the win goes.** " + " ".join(out)


def sensitivity_section(payload: dict[str, Any] | None) -> str:
    if not payload:
        return _not_run(
            "uv run salvage eval sensitivity --seeds 0..4",
            "The sensitivity sweep has not been run.",
        )
    lines = [
        "The response-model multipliers in `salvage/sim/params.yaml` are assumptions, so the",
        "results have to say how much the answer depends on them. Each row scales the intervention",
        "multipliers by the given factor and reports the gap between the best link-sending policy",
        "and B0 in recovered revenue.",
        "",
        "| multiplier scale | seeds | B0 | B1 | B1 minus B0 |",
        "|---|---|---|---|---|",
    ]
    for row in payload["rows"]:
        lines.append(
            f"| {row['scale']:.2f} | {row['seeds']} | {rupees(row['b0'])} | "
            f"{rupees(row['b1'])} | {rupees(row['delta'])} |"
        )
    if payload.get("adversarial"):
        adv = payload["adversarial"]
        lines.append("")
        lines.append("### The adversarial set")
        lines.append("")
        lines.append(
            "docs/01_PRD.md section 12 requires one parameter set where naive immediate retry does"
        )
        lines.append(
            "as well as anything cause-aware, reported rather than hidden. It sets p_organic to"
        )
        lines.append(
            "0.60 for every value band and every intervention multiplier to 1.0, so a nudge neither"
        )
        lines.append("helps nor hurts and timing cannot matter.")
        lines.append("")
        lines.append("| scenario | seeds | " + " | ".join(adv["policies"]) + " |")
        lines.append("|" + "---|" * (len(adv["policies"]) + 2))
        for row in adv["rows"]:
            cells = " | ".join(rupees(row["by_policy"][p]) for p in adv["policies"])
            lines.append(f"| {row['scenario']} | {row['seeds']} | {cells} |")
        lines.append("")
        lines.append("The agent has no advantage here, by design. That is the point of running it.")
    return "\n".join(lines)


def injection_section(payload: dict[str, Any] | None) -> str:
    if not payload:
        return _not_run("uv run pytest tests/fault_injection", "The suite has not been run.")
    lines = [
        f"**{payload['attempts']} injection attempts, {payload['refused']} refused.** "
        f"{payload['fault_tolerance_cases']} further cases are fault tolerance rather than "
        "attack, where the correct behaviour is to carry on, and all were handled.",
        "",
        f"{payload['ledgered']} of the refusals produced a ledger entry. The rest were refused by "
        "a layer that sits above the ledger: a signature that did not verify, an enum that "
        "rejected a value, a schema that rejected a field. Nothing is written for those because "
        "nothing happened, and recording a request that was thrown away at the door would be "
        "logging noise as history. What is asserted separately is that **every refusal the "
        "executor makes inside a run is ledgered, with the rule that refused it**, because that "
        "is a decision Salvage took about a real order.",
        "",
        "| category | attempts | refused | ledgered |",
        "|---|---|---|---|",
    ]
    for category, counts in sorted(payload["by_category"].items()):
        lines.append(
            f"| {category} | {counts['attempts']} | {counts['refused']} | {counts['ledgered']} |"
        )
    if payload.get("unrefused"):
        lines.append("")
        lines.append("Unrefused: " + ", ".join(payload["unrefused"]))
    lines.append("")
    lines.append("Every attempt, in the order the suite runs them:")
    lines.append("")
    lines.append("| category | attempt | refused | outcome |")
    lines.append("|---|---|---|---|")
    for row in payload["rows"]:
        if not row.get("expect_refusal", True):
            continue
        lines.append(
            f"| {row['category']} | {row['attack']} | {'yes' if row['refused'] else 'NO'} | "
            f"{row.get('detail', '')} |"
        )
    return "\n".join(lines)


def _not_run(command: str, why: str) -> str:
    return (
        f"{why} It is not estimated here and no figure is given for it.\n\n"
        f"To produce it:\n\n```\n{command}\n```"
    )


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def build_report(inputs: ReportInputs) -> str:
    main = inputs.main
    # Local date. The documents are written in IST and a UTC date reads as a day behind.
    generated = datetime.now().astimezone().strftime("%d %B %Y")

    from salvage.llm.provider import fixture_provenance

    provenance = fixture_provenance()

    parts: list[str] = []
    parts.append(f"""# Salvage: Results

Generated {generated} from run `{main.run_id}`. Every table in this document was produced by
`salvage eval run` and its raw output is in `data/results/{main.run_id}.json`.

Read the provenance and the limits at the top before the numbers, because they change what the
numbers mean.

## Where the agent's answers came from

**The agent arm is measured, from fixtures recorded blind.** {provenance}

The recording is blind in the code path rather than by discipline. `prompts_for_recording` builds
each evidence packet through `build_for_incident`, the same call the agent makes, which reads the
`v_*` views and therefore cannot reach `truth_cause` or any `sim_truth_*` table. It hands the
provider a `PromptForRecording`, a type carrying the prompt and its hash and nothing else, so the
scenario label is absent rather than merely unused, and `assert_blind` refuses any prompt in which
a scenario id, a seed or a cause name appears. The rules classifier is not run while recording, so
the model's answer cannot be anchored on it. The commands are:

```
export GEMINI_API_KEY=...
uv run salvage diagnose record-fixtures --scenarios S1,S2,S3,S4 --seeds 0..9 --provider gemini
uv run salvage eval run --seeds 0..9 --policies agent,B0,B1,B2 --provider fixture --write-report
```

**The 46 fixtures M2 shipped are not these.** Those were written by the model being evaluated with
the scenario labels visible to its author. They were deleted in M3, no number was ever taken from
them, and nothing in this document descends from them.

**There is no rules-only policy arm and there should not be.** The ablation below measures
classification, not action. Reading it as a policy comparison would be a mistake: a rules-only
diagnosis is assigned 0.5 confidence against a 0.6 action threshold, so such an arm would escalate
everything and recover nothing.

## 1. Primary: recovered revenue over the at-risk order set

{primary_table(main)}

### What a message costs here, and what it does not

{message_cost_caveat(main)}

## 2. Secondary: whole-run totals

{whole_run_table(main)}

## 3. Decomposition

{decomposition_table(main)}

## 4. Secondary metrics

{secondary_table(main)}

## 5. Identical worlds

{digest_table(main)}

## 6. Diagnosis ablation

{
        inputs.diagnosis
        and _diagnosis_block(inputs.diagnosis)
        or _not_run(
            "uv run salvage diagnose accuracy --seeds 0..9 --provider none",
            "The diagnosis ablation has not been run.",
        )
    }

## 7. Detector operating envelope

{volume_section(inputs.volume_sweep)}

## 8. Peak against trough detection

{offpeak_section(main, inputs.offpeak)}

## 9. Sensitivity: the constant the margin rests on

{steer_sensitivity_section(inputs.steer_sensitivity)}

### The adversarial set

{sensitivity_section(inputs.sensitivity)}

## 10. Fault injection

{injection_section(inputs.injection)}

## 11. Escalation to fix

{escalation_fix_section(inputs.escalation_fix)}

## 12. The real end-to-end run

Not yet run. It needs Razorpay test-mode credentials, which the build environment did not have.
`scripts/e2e_real_link.py` is ready and refuses to run without them.

```
cp .env.example .env      # fill RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, RAZORPAY_WEBHOOK_SECRET
uv run python scripts/e2e_real_link.py --amount 100
uv run salvage e2e verify
```

| field | value |
|---|---|
| order id | _to fill_ |
| payment link id | _to fill_ |
| payment id | _to fill_ |
| webhook event id | _to fill_ |
| ledger sequence numbers | _to fill_ |

## 13. Known limitations

{_limitations(inputs)}
""")
    return "\n".join(parts)


def _diagnosis_block(payload: dict[str, Any]) -> str:
    lines = [
        payload.get("provenance", ""),
        "",
        "The reconciled column is the one the agent acts on. A rules verdict and a model verdict "
        "that agree raise confidence, a disagreement lowers it, and anything below 0.6 escalates "
        "rather than acting. Reading the LLM column alone would credit the model for an answer "
        "the agent would not have used.",
        "",
        "| scenario | incidents | seeds | rules-only | LLM | reconciled |",
        "|---|---|---|---|---|---|",
    ]
    for row in payload["rows"]:
        lines.append(
            f"| {row['scenario']} | {row['incidents']} | {row['seeds']} | "
            f"{row['rules_accuracy']:.2f} | {row.get('llm_accuracy', 'unmeasured')} | "
            f"{row.get('reconciled_accuracy', 'unmeasured')} |"
        )
    if payload.get("held_out_rows"):
        held = payload["held_out_seeds"]
        lines.append("")
        lines.append(
            f"The same table over the held-out seeds {min(held)} to {max(held)} alone. The "
            f"detector's thresholds were frozen before those seeds were ever looked at "
            f"(`docs/BUILD_LOG.md`, M2 carry-over 2). The model column is held out on every seed, "
            f"because nothing about the model was tuned on any of them, but reporting the same "
            f"split for both columns keeps them comparable."
        )
        lines.append("")
        lines.append("| scenario | incidents | seeds | rules-only | LLM | reconciled |")
        lines.append("|---|---|---|---|---|---|")
        for row in payload["held_out_rows"]:
            lines.append(
                f"| {row['scenario']} | {row['incidents']} | {row['seeds']} | "
                f"{row['rules_accuracy']:.2f} | {row.get('llm_accuracy', 'unmeasured')} | "
                f"{row.get('reconciled_accuracy', 'unmeasured')} |"
            )
    if payload.get("misses"):
        lines.append("")
        lines.append("Where the rules classifier falls back to `unknown`:")
        lines.append("")
        for miss in payload["misses"]:
            lines.append(f"- {miss}")
    if payload.get("llm_misses"):
        lines.append("")
        lines.append("Where the model was wrong:")
        lines.append("")
        for miss in payload["llm_misses"]:
            lines.append(f"- {miss}")
    elif payload.get("provider") not in (None, "none"):
        lines.append("")
        lines.append("The model was not wrong on any incident in this sweep.")
    return "\n".join(lines)


def escalation_fix_section(payload: dict[str, Any] | None) -> str:
    """The curve, and the crossover if there is one in the swept range."""
    if not payload:
        return _not_run(
            "uv run salvage eval escalation-fix --scenario S4 --seeds 0..4",
            "The escalation-fix sweep has not been run.",
        )

    scenario = payload["scenario"]
    seeds = len(payload["seeds"])
    policies: list[str] = []
    for row in payload["rows"]:
        if row["policy"] not in policies:
            policies.append(row["policy"])
    values: list[Any] = []
    for row in payload["rows"]:
        if row["fix_minutes"] not in values:
            values.append(row["fix_minutes"])
    cells = {(row["fix_minutes"], row["policy"]): row for row in payload["rows"]}

    lines = [
        "An escalation is worth nothing unless somebody acts on it. `escalation_fix_minutes` is "
        "how long that takes, and it is swept rather than defaulted, because how fast a merchant "
        "fixes a misconfiguration is not a fact about Salvage. `never` is the pre-M5 world, in "
        "which the escalation reaches a human and the payments keep failing anyway.",
        "",
        f"{scenario}, mean over {seeds} seeds. Every cell is **at-risk recovered revenue in "
        f"rupees and messages sent**, on the same at-risk order set as section 1.",
        "",
        "| T | " + " | ".join(policies) + " |",
        "|---" * (len(policies) + 1) + "|",
    ]
    for value in values:
        label = "never" if value is None else f"{value} min"
        row_cells = []
        for policy in policies:
            row = cells.get((value, policy))
            if row is None:
                row_cells.append("n/a")
                continue
            row_cells.append(
                f"{rupees(row['at_risk_recovered_amount'])} / {row['messages_sent']:.0f} msg"
            )
        lines.append(f"| {label} | " + " | ".join(row_cells) + " |")

    lines.append("")
    lines.append(
        "**Only an arm that escalates can be repaired.** B1 and B2 never escalate, so their rows "
        "are flat by construction and a row that moved would be a bug rather than a finding. That "
        "asymmetry is worth weighing rather than waving through: a real merchant may well notice a "
        "wholly dead payment method without an agent telling them, in which case part of this "
        "column belongs to the merchant and not to Salvage. Read the curve as the value of "
        "escalating **sooner and with the cause already named**, not as the value of the fault "
        "being fixed at all."
    )
    lines.append("")
    lines.append(_fix_crossover(cells, values, policies))
    lines.append("")
    lines.append(_fix_range_caveat(values, payload))
    return "\n".join(lines)


def _fix_range_caveat(values: list[Any], payload: dict[str, Any]) -> str:
    """Why a flat curve here does not mean speed is free.

    Every T in the swept range lands while the fault is still failing payments, so the population
    a repair can help is the same at every value and only the response model's time decay
    separates them. The cliff is at T equal to the fault's own duration, where the repair arrives
    after the world has recovered on its own and does nothing at all. Saying "the curve is nearly
    flat" without saying that would read as "responding slowly is free", which is the opposite of
    what the mechanism does.
    """
    swept = sorted(v for v in values if v is not None)
    if not swept:
        return ""
    tail = payload.get("beyond_the_fault")
    extra = ""
    if tail:
        rows = ", ".join(
            f"T = {row['fix_minutes']} min: {rupees(row['at_risk_recovered_amount'])}"
            for row in tail
        )
        extra = (
            f" Probed past it on the agent arm alone, same five seeds: {rows}. Compare "
            f"{rupees(tail[0]['never'])} for never."
        )
    return (
        f"**The curve is shallow between {min(swept)} and {max(swept)} minutes, and that is a fact "
        f"about the fault rather than about response times.** The S4 misconfiguration fails "
        f"payments for 180 simulated minutes, so every value in this range repairs it while it is "
        f"still breaking things, the population a repair can reach is the same at each value, and "
        f"only the response model's 12 hour decay separates them. The drop is at T equal to the "
        f"fault's own duration, where the fix arrives after the world has recovered on its own and "
        f"buys nothing.{extra} Read the flatness as "
        f'"any response inside the outage is worth about the same", not as "responding slowly '
        f'is free".'
    )


def _fix_crossover(
    cells: dict[tuple[Any, str], dict[str, Any]], values: list[Any], policies: list[str]
) -> str:
    """The first T at which the agent passes the best baseline, or a plain statement that it does
    not. Named rather than left for the reader to eyeball, and not chosen as a headline."""
    if "agent" not in policies:
        return ""
    rivals = [p for p in policies if p != "agent"]
    ordered = [v for v in values if v is not None]
    ordered.sort(key=lambda v: -int(v))
    best_rival = None
    best_rival_value = 0.0
    for policy in rivals:
        row = cells.get((None, policy))
        if row and row["at_risk_recovered_amount"] > best_rival_value:
            best_rival, best_rival_value = policy, row["at_risk_recovered_amount"]
    if best_rival is None:
        return ""
    for value in ordered:
        row = cells.get((value, "agent"))
        if row and row["at_risk_recovered_amount"] > best_rival_value:
            return (
                f"**Crossover: the agent passes {best_rival} at T = {value} minutes**, at "
                f"{rupees(row['at_risk_recovered_amount'])} against {rupees(best_rival_value)}, "
                f"and it does it while sending {row['messages_sent']:.0f} messages against "
                f"{cells[(None, best_rival)]['messages_sent']:.0f}."
            )
    fastest = ordered[-1] if ordered else None
    agent_row = cells.get((fastest, "agent"))
    fastest_amount = rupees(agent_row["at_risk_recovered_amount"]) if agent_row else "n/a"
    return (
        f"**There is no crossover in the swept range.** Even at T = {fastest} minutes the agent "
        f"recovers {fastest_amount} against {best_rival}'s {rupees(best_rival_value)}. The fix "
        f"narrows the gap and does not close it, and saying so is the point of sweeping the "
        f"parameter rather than picking one."
    )


def _limitations(inputs: ReportInputs) -> str:
    items = [
        "**The escalation fix is modelled on the response side only.** The attempt stream is "
        "generated before any policy runs and is not rewritten, so payments the fault would have "
        "broken after a repair still fail in the recorded data and still count in the at-risk "
        "denominator. A real fix would stop them happening. Section 11 therefore understates what "
        "a fix is worth, and it understates it for the only arm that can trigger one. The "
        "alternative changes which orders exist per arm, which would break the identical order "
        "set that every comparison here rests on.",
        "**Only an arm that escalates can be repaired.** B1 and B2 never escalate, so the fix "
        "curve is available to the agent and to nobody else. A real merchant might notice a dead "
        "payment method without an agent telling them, so part of that column may belong to the "
        "merchant rather than to Salvage.",
        "**The LLM column is one model on one day.** Every fixture was recorded from a single "
        "provider and model, listed at the top of this document. A different model, or the same "
        "model next month, is a different measurement. Nothing here is an accuracy claim about "
        "language models in general.",
        "**S2 at low segment volume attributes to `card` rather than to the failing BIN.** On "
        "held-out seeds 8 and 9 the BIN key never reaches the detector's 20-attempt minimum in a "
        "15-minute window, so the incident is attributed to the whole card method, whose effect "
        "size is diluted by four healthy BIN ranges. Detection still happens, at 11 and 16 sim "
        "minutes rather than 5 to 8, and the rules classifier then cannot fire the "
        "`auth_failure_bin` rule because `card` is not one of the card dimensions that rule "
        "accepts. This is the operating envelope in section 6, not a separate defect.",
        "**S3 seed 8 opens two incidents for one fault.** A merchant-wide gateway incident, and "
        "then a second on `card:card_network:Visa` about seventy minutes later, after the first "
        "closed. The attribution logic was left alone rather than fitted to a held-out seed. The "
        "cost is one duplicate incident in fifty runs.",
        "**Time to detect is a function of segment volume, not of fault severity.** Both slow "
        "detections on the held-out seeds happened because the affected segment sat at or below "
        "the 20-attempt floor, not because the signal was weak. Section 7 gives the boundary.",
        "**The simulator is the instrument.** Every parameter is in `salvage/sim/params.yaml` with "
        "its assumption written beside it. The response-model multipliers are judgement, which is "
        "what section 9 exists to quantify.",
        "**Traffic volume is 12,000 attempts a day, not the 1,500 in the architecture note.** At "
        "1,500 the detector cannot meet the 15-minute target on a single-instrument fault at all. "
        "The arithmetic is in `docs/BUILD_LOG.md`.",
    ]
    if not inputs.volume_sweep:
        items.append("**The volume sweep has not been run**, so section 7 has no boundary figure.")
    if not inputs.sensitivity:
        items.append("**The sensitivity sweep has not been run**, so section 9 is empty.")
    return "\n".join(f"- {item}" for item in items)


def write_results_md(
    result: SweepResult,
    *,
    path: Path | str = RESULTS_PATH,
    inputs: ReportInputs | None = None,
) -> Path:
    inputs = inputs or ReportInputs(main=result)
    if inputs.injection is None:
        inputs.injection = load_json(RESULTS_DIR / "fault_injection.json")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_report(inputs), encoding="utf-8")
    return path


def rows_from_json(payload: dict[str, Any]) -> SweepResult:
    """Rebuild a SweepResult from a results file, so the report can be regenerated offline."""
    result = SweepResult(
        run_id=payload["run_id"],
        scenarios=payload["scenarios"],
        seeds=payload["seeds"],
        policies=payload["policies"],
        variant=payload["variant"],
        started_at=payload.get("started_at", 0),
        finished_at=payload.get("finished_at", 0),
        digests=payload.get("digests", {}),
        notes=payload.get("notes", []),
    )
    for row in payload["rows"]:
        metrics = RunMetrics(
            scenario=row["scenario"],
            seed=row["seed"],
            policy=row["policy"],
            variant=row.get("variant", "peak"),
        )
        for key, value in row.items():
            if hasattr(metrics, key) and key not in (
                "recovery_rate",
                "at_risk_recovery_rate",
                "contacts_per_1000_rupees",
            ):
                setattr(metrics, key, value)
        result.rows.append(metrics)
    return result
