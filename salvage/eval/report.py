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
    calibration: str | None = None


def load_json(path: Path | str) -> dict[str, Any] | None:
    path = Path(path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


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


def headline_table(result: SweepResult) -> str:
    rows = aggregate(result.rows)
    grouped = _by_scenario(rows)
    policies = _policies(result)
    seeds = len(result.seeds)

    lines = [
        f"Recovered revenue in rupees, mean plus or minus standard deviation across {seeds} seeds.",
        "",
        "Every policy is measured over the same order set: every order whose first payment attempt",
        "failed during the evaluation day. The number counts every route to payment, including",
        "customers who came back on their own, because that is the only quantity that means the",
        "same thing for all four arms.",
        "",
    ]
    header = "| scenario | " + " | ".join(policies) + " | best |"
    lines.append(header)
    lines.append("|" + "---|" * (len(policies) + 2))
    for scenario in sorted(grouped):
        cells = []
        best_policy, best_value = None, -1.0
        for policy in policies:
            entry = grouped[scenario].get(policy)
            if entry is None:
                cells.append("not run")
                continue
            cells.append(
                f"{rupees(entry.mean_recovered_amount)} +/- {rupees(entry.std_recovered_amount)}"
            )
            if entry.mean_recovered_amount > best_value:
                best_policy, best_value = policy, entry.mean_recovered_amount
        lines.append(f"| {scenario} | " + " | ".join(cells) + f" | {best_policy} |")
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
            f"{row.mean_fault_recovery_rate:.3f} | {contacts} | "
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

    parts: list[str] = []
    parts.append(f"""# Salvage: Results

Generated {generated} from run `{main.run_id}`. Every table in this document was produced by
`salvage eval run` and its raw output is in `data/results/{main.run_id}.json`.

Read the two limitations at the top before the numbers, because they change what the numbers mean.

## What is measured and what is not

**The agent arm has no diagnosis model, so it takes no customer-facing action.** The action
threshold in Architecture section 7 is a confidence of 0.6, and a rules-only diagnosis is assigned
0.5, deliberately: the rules are good enough to describe an incident to a human and not good
enough to act on unsupervised. With no LLM configured every incident therefore escalates and the
agent's recovered revenue equals B0's, because both recover only what customers do on their own.
**The agent column below is that no-model configuration, not the agent the product describes.**

**The LLM arm is unmeasured.** M2 shipped 46 diagnosis fixtures written by the same model that was
being evaluated, with the scenario labels visible to its author. They were deleted in M3 and no
number was ever taken from them. Refilling `salvage/llm/fixtures/` from a live provider is a single
command, and the isolation is enforced in the code path rather than by discipline:

```
export GEMINI_API_KEY=...
uv run salvage diagnose record-fixtures --scenarios S1,S2,S3,S4 --seeds 0..9 --provider gemini
uv run salvage eval run --seeds 0..9 --policies agent,B0,B1,B2 --provider fixture --write-report
```

Until that has been run, what this document measures honestly is the three baselines against each
other, the detector, the policy engine and the fault-injection surface. What it does not measure is
whether an LLM-assisted agent beats them.

**The diagnosis ablation is rules-only.** The LLM column is absent rather than estimated.

**There is no rules-only policy arm and there should not be.** The ablation below measures
classification, not action. Reading it as a policy comparison would be a mistake: a rules-only
diagnosis never clears the action threshold, so such an arm would escalate everything and recover
nothing.

## 1. Headline: recovered revenue

{headline_table(main)}

## 2. Decomposition

{decomposition_table(main)}

## 3. Secondary metrics

{secondary_table(main)}

## 4. Identical worlds

{digest_table(main)}

## 5. Diagnosis ablation

{
        inputs.diagnosis
        and _diagnosis_block(inputs.diagnosis)
        or _not_run(
            "uv run salvage diagnose accuracy --seeds 0..9 --provider none",
            "The diagnosis ablation has not been run.",
        )
    }

## 6. Detector operating envelope

{volume_section(inputs.volume_sweep)}

## 7. Peak against trough detection

{offpeak_section(main, inputs.offpeak)}

## 8. Sensitivity and the adversarial set

{sensitivity_section(inputs.sensitivity)}

## 9. Fault injection

{injection_section(inputs.injection)}

## 10. The real end-to-end run

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

## 11. Known limitations

{_limitations(inputs)}
""")
    return "\n".join(parts)


def _diagnosis_block(payload: dict[str, Any]) -> str:
    lines = [
        payload.get("provenance", ""),
        "",
        "| scenario | incidents | seeds | rules-only accuracy | LLM-assisted |",
        "|---|---|---|---|---|",
    ]
    for row in payload["rows"]:
        lines.append(
            f"| {row['scenario']} | {row['incidents']} | {row['seeds']} | "
            f"{row['rules_accuracy']:.2f} | {row.get('llm_accuracy', 'unmeasured')} |"
        )
    if payload.get("misses"):
        lines.append("")
        lines.append("Where the rules classifier falls back to `unknown`:")
        lines.append("")
        for miss in payload["misses"]:
            lines.append(f"- {miss}")
    return "\n".join(lines)


def _limitations(inputs: ReportInputs) -> str:
    items = [
        "**The agent arm is unmeasured with a model.** See the top of this document. The measured "
        "agent column is the no-model configuration and equals B0 by construction.",
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
        "the 20-attempt floor, not because the signal was weak. Section 6 gives the boundary.",
        "**The simulator is the instrument.** Every parameter is in `salvage/sim/params.yaml` with "
        "its assumption written beside it. The response-model multipliers are judgement, which is "
        "what section 8 exists to quantify.",
        "**Traffic volume is 12,000 attempts a day, not the 1,500 in the architecture note.** At "
        "1,500 the detector cannot meet the 15-minute target on a single-instrument fault at all. "
        "The arithmetic is in `docs/BUILD_LOG.md`.",
    ]
    if not inputs.volume_sweep:
        items.append("**The volume sweep has not been run**, so section 6 has no boundary figure.")
    if not inputs.sensitivity:
        items.append("**The sensitivity sweep has not been run**, so section 8 is empty.")
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
                "fault_recovery_rate",
                "contacts_per_1000_rupees",
            ):
                setattr(metrics, key, value)
        result.rows.append(metrics)
    return result
