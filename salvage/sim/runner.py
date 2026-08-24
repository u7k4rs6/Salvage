"""Simulator runner.

Drives the sim clock across the warm-up days and the evaluation day, generates traffic, applies
the scenario's faults, pushes every event through the shared normaliser, and writes ground truth.

Architecture section 9 and docs/01_PRD.md section 10. The runner writes ground truth; only the
evaluation runner (M3) reads it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from salvage import repo
from salvage.ingest.normalize import normalize_order_from_payment, normalize_payment_entity
from salvage.ledger import Ledger
from salvage.sim.clock import DAY_SECONDS, SimClock
from salvage.sim.faults import ScheduledFault, schedule
from salvage.sim.merchant import build_catalogue, build_customers, customer_rows
from salvage.sim.params import Params, ParamsError, default_params, load
from salvage.sim.response import ResponseModel
from salvage.sim.rng import Streams
from salvage.sim.traffic import TrafficGenerator, day_starts, eval_day_start

# Rows written per executemany batch. Large enough that the per-statement overhead disappears,
# small enough that a day's rows do not all sit in memory as bound parameters at once.
BATCH_SIZE = 2000


@dataclass(frozen=True)
class SimResult:
    run_id: str
    scenario: str
    seed: int
    attempts: int
    failures: int
    orders: int
    customers: int
    truth_rows: int
    sim_start: int
    sim_end: int
    eval_day_start: int
    scheduled_faults: tuple[ScheduledFault, ...]


def run_id_for(scenario: str, seed: int, params: Params) -> str:
    """Deterministic run id, so re-running the same scenario and seed into a fresh database
    produces the same identifier and results can be compared without a mapping table."""
    return f"run_{scenario}_s{seed}_{params.params_hash[:8]}"


def run_scenario(
    conn,
    *,
    scenario: str,
    seed: int,
    days: int | None = None,
    params_path: Path | str | None = None,
) -> SimResult:
    """Generate one scenario at one seed into an already-migrated database."""
    params = load(params_path) if params_path else default_params()
    scenario_def = params.scenario(scenario)
    if not scenario_def.implemented:
        raise ParamsError(
            f"scenario {scenario} is marked not implemented in params.yaml "
            "(S5 is stretch, see docs/01_PRD.md section 10)"
        )

    eval_days = params.eval_days if days is None else int(days)
    if eval_days < 1:
        raise ParamsError("at least one evaluation day is required")

    streams = Streams(seed)
    catalogue = build_catalogue(params, streams)
    customers = build_customers(params, streams)
    response_model = ResponseModel(params, streams.response)

    clock = SimClock(params.epoch)
    eval_start = eval_day_start(params)
    scheduled = schedule(scenario_def, params, eval_day_start=eval_start, seed=seed)

    run_id = run_id_for(scenario, seed, params)
    ledger = Ledger(conn)

    with _write(conn):
        repo.insert_customers_batch(conn, customer_rows(customers, created_at=params.epoch))
        repo.insert_sim_run(
            conn,
            {
                "run_id": run_id,
                "scenario": scenario,
                "seed": seed,
                "params_hash": params.params_hash,
                "started_at": int(time.time()),
                "finished_at": None,
                "sim_start": params.epoch,
                "sim_end": None,
            },
        )
        for index, fault in enumerate(scheduled):
            repo.insert_truth_incident(
                conn,
                {
                    "id": f"{run_id}_fault_{index}",
                    "run_id": run_id,
                    "scenario": scenario,
                    "segment_selector": repr(fault.fault.selector),
                    "true_cause": fault.fault.truth_cause,
                    "start_ts": fault.start_ts,
                    "end_ts": fault.end_ts,
                },
            )

    # The ledger records the simulated batch as one act, not one act per attempt. See
    # docs/BUILD_LOG.md for why.
    ledger.append(
        "sim.run.started",
        "sim_run",
        run_id,
        {
            "scenario": scenario,
            "seed": seed,
            "params_hash": params.params_hash,
            "warmup_days": params.warmup_days,
            "eval_days": eval_days,
            "faults": [
                {"start_ts": f.start_ts, "end_ts": f.end_ts, "selector": f.fault.selector}
                for f in scheduled
            ],
        },
        ts=params.epoch,
    )

    generator = TrafficGenerator(params, streams, customers, catalogue)
    all_days = day_starts(params)[: params.warmup_days] + [
        eval_start + day * DAY_SECONDS for day in range(eval_days)
    ]

    totals = {"attempts": 0, "failures": 0, "orders": 0, "truth": 0}
    last_ts = params.epoch

    for day_start in all_days:
        clock.set(day_start)
        # Faults only exist on the evaluation day, which is what schedule() places them on; on a
        # warm-up day nothing matches, so the same call is correct for both.
        day_totals, last_ts = _write_day(
            conn, generator, response_model, scheduled, day_start, run_id, last_ts
        )
        for key, value in day_totals.items():
            totals[key] += value
        clock.set(day_start + DAY_SECONDS - 1)

    sim_end = clock.now()
    with _write(conn):
        repo.finish_sim_run(conn, run_id, finished_at=int(time.time()), sim_end=sim_end)

    ledger.append(
        "sim.run.finished",
        "sim_run",
        run_id,
        {
            "attempts": totals["attempts"],
            "failures": totals["failures"],
            "orders": totals["orders"],
            "sim_start": params.epoch,
            "sim_end": sim_end,
        },
        ts=sim_end,
    )

    return SimResult(
        run_id=run_id,
        scenario=scenario,
        seed=seed,
        attempts=totals["attempts"],
        failures=totals["failures"],
        orders=totals["orders"],
        customers=len(customers),
        truth_rows=totals["truth"],
        sim_start=params.epoch,
        sim_end=sim_end,
        eval_day_start=eval_start,
        scheduled_faults=tuple(scheduled),
    )


class _write:
    """A transaction context. db.transaction() would do, but the runner opens and closes many of
    them and this keeps the call sites short."""

    def __init__(self, conn) -> None:
        self._conn = conn

    def __enter__(self):
        self._conn.execute("BEGIN IMMEDIATE")
        return self._conn

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self._conn.execute("COMMIT")
        else:
            self._conn.execute("ROLLBACK")
        return False


def _write_day(
    conn,
    generator: TrafficGenerator,
    response_model: ResponseModel,
    scheduled: list[ScheduledFault],
    day_start: int,
    run_id: str,
    last_ts: int,
) -> tuple[dict[str, int], int]:
    orders: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    truths: list[dict[str, Any]] = []
    totals = {"attempts": 0, "failures": 0, "orders": 0, "truth": 0}

    def flush() -> None:
        if not attempts:
            return
        with _write(conn):
            repo.upsert_orders_batch(conn, orders)
            repo.upsert_attempts_batch(conn, attempts)
            repo.insert_truth_attempts_batch(conn, truths)
        orders.clear()
        attempts.clear()
        truths.clear()

    for generated in generator.generate_day(day_start, scheduled):
        entity = generated.entity
        customer_id = generated.customer_id
        order_row = normalize_order_from_payment(entity, customer_id=customer_id, source="sim")
        attempt_row = normalize_payment_entity(
            entity, customer_id=customer_id, truth_cause=generated.truth_cause
        )
        orders.append(order_row)
        attempts.append(attempt_row)
        totals["attempts"] += 1
        totals["orders"] += 1
        last_ts = max(last_ts, generated.created_at)

        if generated.failed:
            totals["failures"] += 1
            outcome = response_model.draw(
                amount_paise=generated.order_amount,
                failed_at=generated.created_at,
                error_reason=entity.get("error_reason"),
            )
            truths.append(
                {
                    "attempt_id": attempt_row["id"],
                    "run_id": run_id,
                    "fault_caused": int(generated.fault_caused),
                    "truth_cause": generated.truth_cause,
                    "p_organic": outcome.p_organic,
                    "organic_retry_at": outcome.retry_at,
                }
            )
            totals["truth"] += 1

        if len(attempts) >= BATCH_SIZE:
            flush()

    flush()
    return totals, last_ts
