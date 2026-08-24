"""Detector calibration.

Architecture section 5: "the S0 run across five seeds reports incidents per simulated day. The
threshold set above is tuned once on S0 seed 0 and then frozen; seeds 1 to 4 are the held-out
calibration."

`salvage detect calibrate --seeds 0..4` runs S0 to S4 at every seed and prints, per scenario and
seed, incidents opened, time to detect in sim minutes, and false alarms per simulated day.

Each combination runs against its own fresh database, which is deleted as soon as its row is
computed. Architecture section 10 fixes the fresh-database-per-run rule for the evaluation runner
and the same reason applies here: a shared database would let one scenario's warm-up traffic
become another's baseline.

The scratch databases go under data/ rather than the system temporary directory. On this machine
/tmp is a tmpfs, so twenty-five run databases at roughly 100 MB each would be 2.5 GB of RAM on a
laptop with about 11 GB, against a stated budget of 500 MB for an evaluation run (Architecture
section 16). Deleting each database immediately after its row is computed keeps the peak at one.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from salvage.config import get_settings
from salvage.db import open_migrated
from salvage.detect.run import detect
from salvage.detect.thresholds import FROZEN, Thresholds
from salvage.sim.runner import run_scenario

DEFAULT_SCENARIOS = ("S0", "S1", "S2", "S3", "S4")


@dataclass(frozen=True)
class CalibrationRow:
    scenario: str
    seed: int
    variant: str
    eval_days: int
    attempts: int
    incidents_opened: int
    time_to_detect_minutes: float | None
    detected_segment: str | None
    fault_segment: str | None
    false_incidents_per_day: float

    @property
    def detected(self) -> bool:
        return self.time_to_detect_minutes is not None


def run_one(
    scenario: str,
    seed: int,
    *,
    days: int | None = None,
    thresholds: Thresholds = FROZEN,
    params_path: Path | str | None = None,
    workdir: Path | None = None,
    variant: str = "peak",
) -> CalibrationRow:
    """One scenario at one seed, in its own database."""
    own_workdir = workdir is None
    workdir = workdir or make_workdir()
    db_path = workdir / f"{scenario}_{seed}.db"
    try:
        conn = open_migrated(db_path)
        try:
            sim = run_scenario(
                conn,
                scenario=scenario,
                seed=seed,
                days=days,
                params_path=params_path,
                variant=variant,
            )
            # The detector runs over the evaluation days only. The settlement tail carries organic
            # retries and, from M2, link payments; it creates no new orders, so evaluating the
            # detector over it would measure a day of traffic that does not exist.
            eval_days = days if days is not None else _params_eval_days(params_path)
            report = detect(
                conn,
                eval_start=sim.eval_day_start,
                eval_end=sim.eval_day_start + eval_days * 86400,
                thresholds=thresholds,
            )

            fault_start = sim.scheduled_faults[0].start_ts if sim.scheduled_faults else None
            fault_segment = (
                _selector_label(sim.scheduled_faults[0].fault.selector)
                if sim.scheduled_faults
                else None
            )

            time_to_detect = None
            detected_segment = None
            false_incidents = len(report.opened)
            if fault_start is not None:
                for opened in report.opened:
                    if opened.opened_at >= fault_start:
                        time_to_detect = (opened.opened_at - fault_start) / 60.0
                        detected_segment = opened.segment_key
                        false_incidents = len(report.opened) - 1
                        break

            return CalibrationRow(
                scenario=scenario,
                seed=seed,
                variant=variant,
                eval_days=eval_days,
                attempts=sim.attempts,
                incidents_opened=len(report.opened),
                time_to_detect_minutes=time_to_detect,
                detected_segment=detected_segment,
                fault_segment=fault_segment,
                false_incidents_per_day=false_incidents / eval_days,
            )
        finally:
            conn.close()
    finally:
        if own_workdir:
            shutil.rmtree(workdir, ignore_errors=True)
        else:
            # Free the run's database straight away. Holding all twenty-five would be gigabytes.
            for suffix in ("", "-wal", "-shm"):
                Path(str(db_path) + suffix).unlink(missing_ok=True)


def calibrate(
    *,
    scenarios: list[str] | None = None,
    seeds: list[int],
    days: int | None = None,
    thresholds: Thresholds = FROZEN,
    params_path: Path | str | None = None,
    variant: str = "peak",
) -> list[CalibrationRow]:
    scenarios = scenarios or list(DEFAULT_SCENARIOS)
    workdir = make_workdir()
    try:
        return [
            run_one(
                scenario,
                seed,
                days=days,
                thresholds=thresholds,
                params_path=params_path,
                workdir=workdir,
                variant=variant,
            )
            for scenario in scenarios
            for seed in seeds
        ]
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _params_eval_days(params_path: Path | str | None) -> int:
    from salvage.sim.params import default_params, load

    params = load(params_path) if params_path else default_params()
    return params.eval_days


def make_workdir() -> Path:
    """Scratch directory for calibration databases, under data/ rather than the system temp dir."""
    root = Path(get_settings().salvage_db_path).parent / "calibration"
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="run-", dir=root))


def _selector_label(selector: dict[str, str]) -> str:
    if not selector:
        return "all methods"
    return ", ".join(f"{key}={value}" for key, value in sorted(selector.items()))


def format_table(rows: list[CalibrationRow]) -> str:
    """The calibration table, printed by `salvage detect calibrate`."""
    header = (
        f"{'scenario':<9}{'seed':>5}{'attempts':>10}{'incidents':>11}"
        f"{'detect (sim min)':>18}{'false/day':>11}  segment"
    )
    lines = [header, "-" * (len(header) + 20)]
    for row in rows:
        if row.detected:
            detect_text = f"{row.time_to_detect_minutes:.0f}"
        else:
            detect_text = "n/a" if row.scenario == "S0" else "MISSED"
        segment = row.detected_segment or (row.fault_segment or "")
        lines.append(
            f"{row.scenario:<9}{row.seed:>5}{row.attempts:>10}{row.incidents_opened:>11}"
            f"{detect_text:>18}{row.false_incidents_per_day:>11.2f}  {segment}"
        )

    lines.append("")
    lines.append(summarise(rows))
    return "\n".join(lines)


def summarise(rows: list[CalibrationRow]) -> str:
    """The two numbers the exit criteria are stated in."""
    fault_rows = [row for row in rows if row.scenario != "S0"]
    s0_rows = [row for row in rows if row.scenario == "S0"]
    parts: list[str] = []

    if fault_rows:
        missed = [f"{r.scenario}/seed {r.seed}" for r in fault_rows if not r.detected]
        latencies = [r.time_to_detect_minutes for r in fault_rows if r.detected]
        worst = max(latencies) if latencies else float("nan")
        parts.append(
            f"S1 to S4: {len(latencies)}/{len(fault_rows)} detected, "
            f"worst time to detect {worst:.0f} sim minutes"
            + (f", missed: {', '.join(missed)}" if missed else "")
        )
    if s0_rows:
        held_out = [row for row in s0_rows if row.seed != 0]
        total_days = sum(row.eval_days for row in s0_rows)
        total_incidents = sum(row.incidents_opened for row in s0_rows)
        parts.append(
            f"S0 all seeds: {total_incidents} incident(s) over {total_days} simulated day(s) "
            f"= {total_incidents / total_days:.2f} per day"
        )
        if held_out:
            held_days = sum(row.eval_days for row in held_out)
            held_incidents = sum(row.incidents_opened for row in held_out)
            parts.append(
                f"S0 held-out seeds {min(r.seed for r in held_out)} to "
                f"{max(r.seed for r in held_out)}: {held_incidents} incident(s) over "
                f"{held_days} day(s) = {held_incidents / held_days:.2f} per day"
            )
    return "\n".join(parts)
