"""The evaluation sweep.

Architecture section 10:

  `salvage eval run --scenarios S0,S1,S2,S3,S4 --seeds 0..9 --policies agent,B0,B1,B2` runs each
  combination in isolation (fresh database per run), collects the metrics in PRD section 11, and
  writes data/results/<run_id>.json plus docs/RESULTS.md.

Two rules this file exists to keep:

  A fresh database per run, deleted as soon as its metrics are collected. Peak disk is one run's
  database, not two hundred. The M1 build log records what happens otherwise: the scratch
  databases went to a tmpfs and took the machine's memory with them.

  Only this module and salvage/eval/metrics.py read simulator ground truth. The fault windows come
  from the SimResult the runner already has; nothing downstream of a policy ever sees them.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from salvage.db import open_migrated
from salvage.detect.calibrate import make_workdir
from salvage.eval.agent_run import run_policy_scenario
from salvage.eval.baselines import DEFAULT_POLICY_ORDER
from salvage.eval.metrics import RunMetrics
from salvage.sim.params import default_params

DEFAULT_SCENARIOS = ("S0", "S1", "S2", "S3", "S4")


@dataclass
class SweepResult:
    run_id: str
    scenarios: list[str]
    seeds: list[int]
    policies: list[str]
    variant: str
    rows: list[RunMetrics] = field(default_factory=list)
    digests: dict[str, dict[str, str]] = field(default_factory=dict)
    started_at: int = 0
    finished_at: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def wall_seconds(self) -> int:
        return max(0, self.finished_at - self.started_at)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "scenarios": self.scenarios,
            "seeds": self.seeds,
            "policies": self.policies,
            "variant": self.variant,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "wall_seconds": self.wall_seconds,
            "notes": self.notes,
            "digests": self.digests,
            "rows": [row.as_dict() for row in self.rows],
        }


def sweep(
    *,
    scenarios: list[str] | None = None,
    seeds: list[int],
    policies: list[str] | None = None,
    variant: str = "peak",
    provider=None,
    params_path: Path | str | None = None,
    run_id: str | None = None,
    progress=None,
) -> SweepResult:
    """Every (scenario, seed, policy) combination, each in its own database."""
    scenarios = list(scenarios or DEFAULT_SCENARIOS)
    policies = list(policies or DEFAULT_POLICY_ORDER)
    started = int(time.time())
    result = SweepResult(
        run_id=run_id or f"sweep_{started}",
        scenarios=scenarios,
        seeds=list(seeds),
        policies=policies,
        variant=variant,
        started_at=started,
    )

    workdir = make_workdir()
    try:
        total = len(scenarios) * len(seeds) * len(policies)
        done = 0
        for scenario in scenarios:
            for seed in seeds:
                key = f"{scenario}/{seed}"
                result.digests.setdefault(key, {})
                for policy in policies:
                    metrics, digest = _one(
                        workdir=workdir,
                        scenario=scenario,
                        seed=seed,
                        policy=policy,
                        variant=variant,
                        provider=provider,
                        params_path=params_path,
                    )
                    result.rows.append(metrics)
                    result.digests[key][policy] = digest
                    done += 1
                    if progress is not None:
                        progress(done, total, scenario, seed, policy, metrics)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    result.finished_at = int(time.time())
    result.notes.extend(_digest_notes(result))
    return result


def _one(
    *, workdir: Path, scenario: str, seed: int, policy: str, variant: str, provider, params_path
) -> tuple[RunMetrics, str]:
    db_path = workdir / f"{scenario}_{seed}_{policy}_{variant}.db"
    conn = open_migrated(db_path)
    try:
        run = run_policy_scenario(
            conn,
            scenario=scenario,
            seed=seed,
            policy=policy,
            variant=variant,
            provider=provider,
            params_path=params_path,
        )
        return run.metrics, run.stream_digest
    finally:
        conn.close()
        # Deleted immediately, so peak disk is one run's database.
        for suffix in ("", "-wal", "-shm"):
            Path(str(db_path) + suffix).unlink(missing_ok=True)


def _digest_notes(result: SweepResult) -> list[str]:
    """One note per (scenario, seed) whose policies did not all see the same world."""
    notes = []
    for key, digests in sorted(result.digests.items()):
        if len(set(digests.values())) > 1:
            notes.append(
                f"WORLD MISMATCH at {key}: policies saw different attempt streams {digests}"
            )
    return notes


def digests_match(result: SweepResult) -> bool:
    return all(len(set(d.values())) <= 1 for d in result.digests.values())


def write_results_json(result: SweepResult, directory: Path | str = "data/results") -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{result.run_id}.json"
    path.write_text(json.dumps(result.as_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Aggregate:
    """Mean and standard deviation across seeds for one (scenario, policy)."""

    scenario: str
    policy: str
    seeds: int
    mean_recovered_amount: float
    std_recovered_amount: float
    mean_recovered_orders: float
    mean_recovery_rate: float
    mean_fault_recovery_rate: float
    mean_messages: float
    mean_contacts_per_1000: float
    mean_link_orders: float
    mean_steer_orders: float
    mean_organic_orders: float
    total_violations: int
    mean_escalations: float
    detected: int
    mean_time_to_detect: float | None


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float]) -> float:
    """Population standard deviation. One seed gives zero, which is honest: with one sample there
    is no spread to report, and docs/01_PRD.md section 12 forbids single-seed numbers anyway."""
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    return (sum((value - mean) ** 2 for value in values) / len(values)) ** 0.5


def aggregate(rows: list[RunMetrics]) -> list[Aggregate]:
    grouped: dict[tuple[str, str], list[RunMetrics]] = {}
    for row in rows:
        grouped.setdefault((row.scenario, row.policy), []).append(row)

    out = []
    for (scenario, policy), group in sorted(grouped.items()):
        latencies = [
            row.time_to_detect_minutes
            for row in group
            if row.time_to_detect_minutes is not None
        ]
        finite_contacts = [
            row.contacts_per_1000_rupees
            for row in group
            if row.contacts_per_1000_rupees != float("inf")
        ]
        out.append(
            Aggregate(
                scenario=scenario,
                policy=policy,
                seeds=len(group),
                mean_recovered_amount=_mean([row.recovered_amount for row in group]),
                std_recovered_amount=_std([float(row.recovered_amount) for row in group]),
                mean_recovered_orders=_mean([row.recovered_orders for row in group]),
                mean_recovery_rate=_mean([row.recovery_rate for row in group]),
                mean_fault_recovery_rate=_mean([row.fault_recovery_rate for row in group]),
                mean_messages=_mean([row.messages_sent for row in group]),
                mean_contacts_per_1000=_mean(finite_contacts),
                mean_link_orders=_mean([row.by_route_orders.get("link", 0) for row in group]),
                mean_steer_orders=_mean([row.by_route_orders.get("steer", 0) for row in group]),
                mean_organic_orders=_mean(
                    [row.by_route_orders.get("organic", 0) for row in group]
                ),
                total_violations=sum(row.policy_violations for row in group),
                mean_escalations=_mean([row.escalations for row in group]),
                detected=len(latencies),
                mean_time_to_detect=_mean(latencies) if latencies else None,
            )
        )
    return out


def eval_window_days() -> int:
    return default_params().eval_days


# ---------------------------------------------------------------------------
# Parameter overrides
# ---------------------------------------------------------------------------


def params_with(overrides: dict[str, Any], directory: Path) -> Path:
    """A copy of the shipped params.yaml with some values replaced.

    Overrides are dotted paths, for example "traffic.attempts_per_day". Writing a file rather than
    mutating the loaded object keeps the runs honest in one specific way: `params_hash` changes
    with the file, so a result produced under a swept parameter set cannot be mistaken for one
    produced under the shipped set.
    """
    import yaml

    from salvage.sim.params import PARAMS_PATH

    raw = yaml.safe_load(PARAMS_PATH.read_text(encoding="utf-8"))
    for dotted, value in overrides.items():
        node = raw
        parts = dotted.split(".")
        for part in parts[:-1]:
            node = node[part]
        node[parts[-1]] = value
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "params.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Volume sweep: the detector's operating envelope
# ---------------------------------------------------------------------------

DEFAULT_VOLUMES = (1500, 5000, 12000)


def volume_sweep(
    *,
    scenarios: list[str],
    seeds: list[int],
    volumes: tuple[int, ...] = DEFAULT_VOLUMES,
    variant: str = "peak",
) -> dict[str, Any]:
    """The same fault at several merchant volumes.

    docs/02_TECHNICAL_ARCHITECTURE.md section 5 will not evaluate a segment key with fewer than 20
    attempts in a 15-minute window. That makes time to detect a function of the affected segment's
    volume, and it means there is a merchant size below which a single-instrument fault cannot be
    detected inside 15 minutes at all. This measures where that boundary falls instead of asserting
    it.

    Only B0 is run: detection happens for every policy and does not depend on which one is acting,
    so running four arms would cost four times the wall clock for identical detector numbers.
    """
    rows: list[dict[str, Any]] = []
    workdir = make_workdir()
    try:
        for volume in volumes:
            params_path = params_with(
                {"traffic.attempts_per_day": volume},
                workdir / f"v{volume}",
            )
            for scenario in scenarios:
                latencies: list[float] = []
                segments: list[str] = []
                for seed in seeds:
                    db_path = workdir / f"vol_{volume}_{scenario}_{seed}.db"
                    conn = open_migrated(db_path)
                    try:
                        run = run_policy_scenario(
                            conn,
                            scenario=scenario,
                            seed=seed,
                            policy="B0",
                            variant=variant,
                            params_path=params_path,
                        )
                        if run.metrics.time_to_detect_minutes is not None:
                            latencies.append(run.metrics.time_to_detect_minutes)
                            segments.extend(
                                str(incident["segment_key"])
                                for incident in run.incidents
                                if not str(incident["id"]).endswith("_baseline")
                            )
                    finally:
                        conn.close()
                        for suffix in ("", "-wal", "-shm"):
                            Path(str(db_path) + suffix).unlink(missing_ok=True)
                rows.append(
                    {
                        "attempts_per_day": volume,
                        "scenario": scenario,
                        "seeds": len(seeds),
                        "detected": len(latencies),
                        "mean_time_to_detect": _mean(latencies) if latencies else None,
                        "worst_time_to_detect": max(latencies) if latencies else None,
                        "within_15_minutes": sum(1 for value in latencies if value < 15),
                        "segments": ", ".join(sorted(set(segments))) if segments else "",
                    }
                )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    return {"volumes": list(volumes), "rows": rows, "boundary": _volume_boundary(rows)}


def _volume_boundary(rows: list[dict[str, Any]]) -> str:
    """One sentence saying where 15-minute detection stops working."""
    by_volume: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        by_volume.setdefault(int(row["attempts_per_day"]), []).append(row)

    verdicts = []
    for volume in sorted(by_volume):
        group = by_volume[volume]
        seeds = sum(row["seeds"] for row in group)
        detected = sum(row["detected"] for row in group)
        inside = sum(row["within_15_minutes"] for row in group)
        verdicts.append(
            f"At {volume:,} attempts a day: {detected} of {seeds} faults detected at all, "
            f"{inside} of {seeds} inside 15 sim minutes."
        )
    return "\n".join(verdicts)


# ---------------------------------------------------------------------------
# Sensitivity and the adversarial set
# ---------------------------------------------------------------------------

DEFAULT_SENSITIVITY_SCALES = (0.5, 0.75, 1.0, 1.5, 2.0)


def sensitivity_sweep(
    *,
    scenario: str,
    seeds: list[int],
    scales: tuple[float, ...] = DEFAULT_SENSITIVITY_SCALES,
    policies: tuple[str, ...] = ("B0", "B1"),
) -> dict[str, Any]:
    """How much the answer depends on the response-model multipliers.

    docs/01_PRD.md section 12: the results include a sensitivity sweep over the response-model
    multipliers. Each scale multiplies both intervention multipliers, so a scale of 0.5 halves how
    much any nudge helps and a scale of 2.0 doubles it. The reported gap is between the best
    link-sending policy and B0, because that is the quantity the whole product rests on.
    """
    from salvage.sim.params import default_params

    base = default_params().response["m2_multipliers"]
    rows: list[dict[str, Any]] = []
    workdir = make_workdir()
    try:
        for scale in scales:
            params_path = params_with(
                {
                    "response.m2_multipliers": {
                        **base,
                        "nudge_while_method_still_failing": round(
                            base["nudge_while_method_still_failing"] * scale, 4
                        ),
                        "nudge_after_recovery_or_with_alternate": round(
                            base["nudge_after_recovery_or_with_alternate"] * scale, 4
                        ),
                    }
                },
                workdir / f"s{scale}",
            )
            totals: dict[str, list[float]] = {policy: [] for policy in policies}
            for policy in policies:
                for seed in seeds:
                    db_path = workdir / f"sens_{scale}_{policy}_{seed}.db"
                    conn = open_migrated(db_path)
                    try:
                        run = run_policy_scenario(
                            conn,
                            scenario=scenario,
                            seed=seed,
                            policy=policy,
                            params_path=params_path,
                        )
                        totals[policy].append(float(run.metrics.recovered_amount))
                    finally:
                        conn.close()
                        for suffix in ("", "-wal", "-shm"):
                            Path(str(db_path) + suffix).unlink(missing_ok=True)
            b0, b1 = _mean(totals.get("B0", [])), _mean(totals.get("B1", []))
            rows.append(
                {
                    "scale": scale,
                    "seeds": len(seeds),
                    "b0": b0,
                    "b1": b1,
                    "delta": b1 - b0,
                }
            )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return {"scenario": scenario, "rows": rows}


def adversarial_sweep(
    *,
    scenarios: list[str],
    seeds: list[int],
    policies: tuple[str, ...] = ("B0", "B1", "B2"),
) -> dict[str, Any]:
    """The adversarial parameter set from docs/01_PRD.md section 12.

    p_organic 0.60 for every value band and every intervention multiplier 1.0, so a nudge neither
    helps nor hurts and cause-aware timing cannot matter. Any policy that still looks better here
    is measuring noise, which is exactly why the set exists.
    """
    from salvage.sim.params import default_params

    adversarial = default_params().response["m2_adversarial"]
    flat = float(adversarial["p_organic_flat"])
    unit = float(adversarial["all_multipliers"])
    base = default_params().response["m2_multipliers"]

    workdir = make_workdir()
    rows: list[dict[str, Any]] = []
    try:
        params_path = params_with(
            {
                "response.p_organic_by_value_band": [
                    {"max_paise": 50000, "p": flat},
                    {"max_paise": 150000, "p": flat},
                    {"max_paise": 300000, "p": flat},
                    {"max_paise": None, "p": flat},
                ],
                "response.m2_multipliers": {
                    **base,
                    "nudge_while_method_still_failing": unit,
                    "nudge_after_recovery_or_with_alternate": unit,
                    "second_nudge_multiplier": unit,
                    "live_checkout_steer_during_failing_session": unit,
                },
            },
            workdir / "adversarial",
        )
        for scenario in scenarios:
            by_policy: dict[str, float] = {}
            for policy in policies:
                totals = []
                for seed in seeds:
                    db_path = workdir / f"adv_{scenario}_{policy}_{seed}.db"
                    conn = open_migrated(db_path)
                    try:
                        run = run_policy_scenario(
                            conn,
                            scenario=scenario,
                            seed=seed,
                            policy=policy,
                            params_path=params_path,
                        )
                        totals.append(float(run.metrics.recovered_amount))
                    finally:
                        conn.close()
                        for suffix in ("", "-wal", "-shm"):
                            Path(str(db_path) + suffix).unlink(missing_ok=True)
                by_policy[policy] = _mean(totals)
            rows.append({"scenario": scenario, "seeds": len(seeds), "by_policy": by_policy})
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return {"policies": list(policies), "rows": rows}
