"""Simulator runner.

Drives the sim clock across the warm-up days, the evaluation day and the settlement tail,
generates traffic, applies the scenario's faults, pushes every event through the shared
normaliser, and writes ground truth.

Architecture section 9 and docs/01_PRD.md section 10. The runner writes ground truth; only the
evaluation runner reads it.

Two things here are not in the M1 version and are worth knowing about before reading the code:

  Organic retries. A failed order draws a chain of retries from its own random stream, and those
  retries are real payment attempts on the same order with the same instrument. A run therefore
  has more attempts than orders, and a retry that lands while the rail is still broken fails
  again. That is the behaviour that makes cause-aware timing worth anything.

  Stream commitment. sim.run.finished carries a sha256 over the ordered attempt stream, so the
  ledger commits to the events, not just to the counts. `salvage sim verify-stream` recomputes it.
"""

from __future__ import annotations

import hashlib
import heapq
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from salvage import repo
from salvage.ingest.normalize import normalize_order_from_payment, normalize_payment_entity
from salvage.ledger import Ledger
from salvage.sim.clock import DAY_SECONDS, SimClock
from salvage.sim.faults import ScheduledFault, schedule
from salvage.sim.merchant import SimCustomer, build_catalogue, build_customers, customer_rows
from salvage.sim.params import Params, ParamsError, default_params, load
from salvage.sim.response import ResponseModel
from salvage.sim.rng import Streams
from salvage.sim.traffic import GeneratedAttempt, TrafficGenerator, eval_day_start

# Rows written per executemany batch. Large enough that the per-statement overhead disappears,
# small enough that a day's rows do not all sit in memory as bound parameters at once.
BATCH_SIZE = 2000

# How long before a configuration-changing fault the merchant's config change is recorded.
# Assumption: somebody saves a setting, and the errors start on the next payment. Five minutes is
# short enough to be causally obvious and long enough that the change is visible in the evidence
# packet before the first window closes.
CONFIG_CHANGE_LEAD_SECONDS = 300

# Fields the ledger's stream commitment covers, in this order. Changing this list changes every
# digest ever computed, so it lives in one place and salvage/sim/verify.py reads it from here.
STREAM_FIELDS = ("id", "order_id", "method", "instrument", "status", "error_code", "created_at")


@dataclass(frozen=True)
class SimResult:
    run_id: str
    scenario: str
    seed: int
    variant: str
    attempts: int
    first_attempts: int
    retries: int
    failures: int
    orders: int
    orders_paid: int
    orders_paid_on_retry: int
    customers: int
    truth_rows: int
    sim_start: int
    sim_end: int
    eval_day_start: int
    stream_digest: str
    dropped_retries: int
    scheduled_faults: tuple[ScheduledFault, ...] = ()


@dataclass(order=True)
class _PendingRetry:
    """One planned organic retry, waiting for its moment."""

    at: int
    sequence: int
    order_id: str = field(compare=False)
    order_index: int = field(compare=False)
    customer_index: int = field(compare=False)
    amount: int = field(compare=False)
    retry_index: int = field(compare=False)
    failure_draw: float = field(compare=False)
    profile_draw: float = field(compare=False)
    p_organic: float = field(compare=False)


def run_id_for(scenario: str, seed: int, params: Params, variant: str = "peak") -> str:
    """Deterministic run id, so re-running the same scenario and seed into a fresh database
    produces the same identifier and results can be compared without a mapping table."""
    suffix = "" if variant == "peak" else f"_{variant}"
    return f"run_{scenario}{suffix}_s{seed}_{params.params_hash[:8]}"


def instrument_label(row: dict[str, Any]) -> str:
    """Canonical instrument identity for the stream commitment.

    One string rather than five columns, so the digest's input is unambiguous and a null and an
    empty string cannot collide.
    """
    parts = [
        row.get("upi_handle") or "",
        row.get("card_bin") or "",
        row.get("card_network") or "",
        row.get("card_issuer") or "",
        row.get("nb_bank") or "",
    ]
    return "|".join(parts)


def stream_digest(conn, *, sim_start: int, sim_end: int) -> tuple[str, int]:
    """sha256 over the ordered attempt stream, and the number of attempts covered.

    Ordering is (created_at, id), stated explicitly rather than relying on insertion order, so the
    runner and `salvage sim verify-stream` compute the same thing from the same query.

    Reads v_payment_attempts, so the digest cannot accidentally commit to ground truth.
    """
    digest = hashlib.sha256()
    digest.update(b"salvage.sim.stream.v1\n")
    count = 0
    rows = conn.execute(
        "SELECT id, order_id, method, upi_handle, card_bin, card_network, card_issuer, nb_bank, "
        "status, error_code, created_at FROM v_payment_attempts "
        "WHERE created_at >= ? AND created_at <= ? ORDER BY created_at, id",
        (sim_start, sim_end),
    )
    for row in rows:
        record = dict(row)
        values = (
            record["id"],
            record["order_id"],
            record["method"],
            instrument_label(record),
            record["status"],
            record["error_code"] or "",
            str(record["created_at"]),
        )
        for value in values:
            digest.update(str(value).encode("utf-8"))
            digest.update(b"\x1f")
        digest.update(b"\x1e")
        count += 1
    return digest.hexdigest(), count


def run_scenario(
    conn,
    *,
    scenario: str,
    seed: int,
    days: int | None = None,
    params_path: Path | str | None = None,
    variant: str = "peak",
) -> SimResult:
    """Generate one scenario at one seed into an already-migrated database."""
    params = load(params_path) if params_path else default_params()
    scenario_def = params.scenario(scenario)
    if not scenario_def.implemented:
        raise ParamsError(
            f"scenario {scenario} is marked not implemented in params.yaml "
            "(S5 is stretch, see docs/01_PRD.md section 10)"
        )
    params.variant(variant)  # raises on an unknown variant before any work is done

    eval_days = params.eval_days if days is None else int(days)
    if eval_days < 1:
        raise ParamsError("at least one evaluation day is required")

    streams = Streams(seed)
    catalogue = build_catalogue(params, streams)
    customers = build_customers(params, streams)
    customer_index = {customer.customer_id: index for index, customer in enumerate(customers)}
    response_model = ResponseModel(params, seed)

    clock = SimClock(params.epoch)
    eval_start = eval_day_start(params)
    scheduled = schedule(
        scenario_def, params, eval_day_start=eval_start, seed=seed, variant=variant
    )

    run_id = run_id_for(scenario, seed, params, variant)
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
            if fault.fault.sets_config_changed_flag:
                # A merchant-side fact, not ground truth: the agent reads config_changes like any
                # other merchant signal. Timed before the errors start, because that is the causal
                # order and because a classifier that only ever sees the change at the same
                # instant as the errors is being handed the answer.
                repo.insert_config_change(
                    conn,
                    {
                        "id": f"{run_id}_cfg_{index}",
                        "changed_at": fault.start_ts - CONFIG_CHANGE_LEAD_SECONDS,
                        "area": "payment_methods",
                        "detail": "payment method configuration updated",
                        "source": "sim",
                    },
                )
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

    # The ledger records the simulated batch as one act, not one act per attempt. The commitment
    # in sim.run.finished is what ties that one entry to every event in the batch.
    ledger.append(
        "sim.run.started",
        "sim_run",
        run_id,
        {
            "scenario": scenario,
            "seed": seed,
            "variant": variant,
            "params_hash": params.params_hash,
            "warmup_days": params.warmup_days,
            "eval_days": eval_days,
            "settle_days": params.settle_days,
            "attempts_per_day": params.attempts_per_day(scenario),
            "faults": [
                {"start_ts": f.start_ts, "end_ts": f.end_ts, "selector": f.fault.selector}
                for f in scheduled
            ],
        },
        ts=params.epoch,
    )

    generator = TrafficGenerator(params, streams, customers, catalogue, scenario_id=scenario)
    generating_days = [params.epoch + day * DAY_SECONDS for day in range(params.warmup_days)] + [
        eval_start + day * DAY_SECONDS for day in range(eval_days)
    ]
    settle_days = [
        eval_start + (eval_days + day) * DAY_SECONDS for day in range(params.settle_days)
    ]
    all_days = generating_days + settle_days
    sim_end = all_days[-1] + DAY_SECONDS - 1

    state = _RunState(
        conn=conn,
        generator=generator,
        response_model=response_model,
        customers=customers,
        customer_index=customer_index,
        scheduled=scheduled,
        run_id=run_id,
    )

    for day_start in all_days:
        clock.set(day_start)
        state.run_day(day_start, generate=day_start in set(generating_days))
        clock.set(day_start + DAY_SECONDS - 1)
    state.drain_after(sim_end)
    state.flush()

    digest, digest_count = stream_digest(conn, sim_start=params.epoch, sim_end=sim_end)

    with _write(conn):
        repo.finish_sim_run(conn, run_id, finished_at=int(time.time()), sim_end=sim_end)

    ledger.append(
        "sim.run.finished",
        "sim_run",
        run_id,
        {
            "attempts": state.totals["attempts"],
            "first_attempts": state.totals["first_attempts"],
            "retries": state.totals["retries"],
            "failures": state.totals["failures"],
            "orders": state.totals["orders"],
            "orders_paid": state.totals["orders_paid"],
            "orders_paid_on_retry": state.totals["orders_paid_on_retry"],
            "dropped_retries": state.totals["dropped_retries"],
            "sim_start": params.epoch,
            "sim_end": sim_end,
            # The commitment. Everything above is a count; this is what makes the ledger entry a
            # statement about the events themselves.
            "stream_digest": digest,
            "stream_attempts": digest_count,
            "stream_fields": list(STREAM_FIELDS),
        },
        ts=sim_end,
    )

    return SimResult(
        run_id=run_id,
        scenario=scenario,
        seed=seed,
        variant=variant,
        attempts=state.totals["attempts"],
        first_attempts=state.totals["first_attempts"],
        retries=state.totals["retries"],
        failures=state.totals["failures"],
        orders=state.totals["orders"],
        orders_paid=state.totals["orders_paid"],
        orders_paid_on_retry=state.totals["orders_paid_on_retry"],
        customers=len(customers),
        truth_rows=state.totals["truth"],
        sim_start=params.epoch,
        sim_end=sim_end,
        eval_day_start=eval_start,
        stream_digest=digest,
        dropped_retries=state.totals["dropped_retries"],
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


class _RunState:
    """Buffers, counters and the pending-retry queue for one run."""

    def __init__(
        self,
        *,
        conn,
        generator: TrafficGenerator,
        response_model: ResponseModel,
        customers: list[SimCustomer],
        customer_index: dict[str, int],
        scheduled: list[ScheduledFault],
        run_id: str,
    ) -> None:
        self._conn = conn
        self._generator = generator
        self._response = response_model
        self._customers = customers
        self._customer_index = customer_index
        self._scheduled = scheduled
        self._run_id = run_id

        self._orders: list[dict[str, Any]] = []
        self._attempts: list[dict[str, Any]] = []
        self._truths: list[dict[str, Any]] = []
        self._pending: list[_PendingRetry] = []
        self._sequence = 0
        # Orders that reached paid. Kept in memory so a retry does not need a database read.
        self._paid: set[str] = set()

        self.totals: dict[str, int] = {
            "attempts": 0,
            "first_attempts": 0,
            "retries": 0,
            "failures": 0,
            "orders": 0,
            "orders_paid": 0,
            "orders_paid_on_retry": 0,
            "truth": 0,
            "dropped_retries": 0,
        }

    # -- the day loop ------------------------------------------------------

    def run_day(self, day_start: int, *, generate: bool) -> None:
        """One simulated day: new orders merged with organic retries, in time order.

        On a settlement day nothing new is created and only the queue drains.
        """
        day_end = day_start + DAY_SECONDS
        stream = (
            self._generator.generate_day(day_start, self._scheduled)
            if generate
            else iter(())
        )
        for generated in stream:
            self._drain_until(generated.created_at)
            self._record(generated)
        self._drain_until(day_end)

    def drain_after(self, sim_end: int) -> None:
        """Anything still queued past the end of the simulation is dropped and counted.

        Counted rather than silently discarded: if this number is not small, the settlement tail
        is too short and every recovery figure in docs/RESULTS.md is understated.
        """
        self._drain_until(sim_end + 1)
        self.totals["dropped_retries"] += len(self._pending)
        self._pending.clear()

    def _drain_until(self, ts: int) -> None:
        while self._pending and self._pending[0].at < ts:
            pending = heapq.heappop(self._pending)
            if pending.order_id in self._paid:
                # The order was paid before this retry came due, so the customer never made it.
                continue
            customer = self._customers[pending.customer_index]
            generated = self._generator.retry(
                ts=pending.at,
                customer=customer,
                order_id=pending.order_id,
                order_index=pending.order_index,
                amount=pending.amount,
                retry_index=pending.retry_index + 1,
                failure_draw=pending.failure_draw,
                profile_draw=pending.profile_draw,
                scheduled=self._scheduled,
            )
            self._record(generated, p_organic=pending.p_organic)

    # -- recording ---------------------------------------------------------

    def _record(self, generated: GeneratedAttempt, *, p_organic: float | None = None) -> None:
        entity = generated.entity
        customer_id = generated.customer_id
        order_row = normalize_order_from_payment(entity, customer_id=customer_id, source="sim")
        attempt_row = normalize_payment_entity(
            entity, customer_id=customer_id, truth_cause=generated.truth_cause
        )
        self._orders.append(order_row)
        self._attempts.append(attempt_row)

        self.totals["attempts"] += 1
        if generated.is_retry:
            self.totals["retries"] += 1
        else:
            self.totals["first_attempts"] += 1
            self.totals["orders"] += 1

        if not generated.failed:
            self._paid.add(generated.order_id)
            self.totals["orders_paid"] += 1
            if generated.is_retry:
                self.totals["orders_paid_on_retry"] += 1
        else:
            self.totals["failures"] += 1
            self._on_failure(generated, p_organic=p_organic)

        if len(self._attempts) >= BATCH_SIZE:
            self.flush()

    def _on_failure(self, generated: GeneratedAttempt, *, p_organic: float | None) -> None:
        """Ground truth for a failed attempt, and the retry chain if this is the first failure."""
        next_retry_at: int | None = None
        if not generated.is_retry:
            plan = self._response.organic_plan(
                order_index=generated.order_index,
                amount_paise=generated.order_amount,
                first_failed_at=generated.created_at,
                error_reason=generated.error_reason,
            )
            p_organic = plan.p_organic
            next_retry_at = plan.first_retry_at
            for retry in plan.retries:
                self._sequence += 1
                heapq.heappush(
                    self._pending,
                    _PendingRetry(
                        at=retry.at,
                        sequence=self._sequence,
                        order_id=generated.order_id,
                        order_index=generated.order_index,
                        customer_index=self._customer_index[generated.customer_id],
                        amount=generated.order_amount,
                        retry_index=retry.retry_index,
                        failure_draw=retry.failure_draw,
                        profile_draw=retry.profile_draw,
                        p_organic=plan.p_organic,
                    ),
                )
        else:
            # The chain was drawn when the order first failed; the remaining retries are already
            # queued. The next one, if any, is whatever sits in the queue for this order.
            next_retry_at = next(
                (p.at for p in sorted(self._pending) if p.order_id == generated.order_id), None
            )

        self._truths.append(
            {
                "attempt_id": generated.entity["id"],
                "run_id": self._run_id,
                "fault_caused": int(generated.fault_caused),
                "truth_cause": generated.truth_cause,
                "p_organic": float(p_organic if p_organic is not None else 0.0),
                "organic_retry_at": next_retry_at,
            }
        )
        self.totals["truth"] += 1

    def flush(self) -> None:
        if not self._attempts:
            return
        with _write(self._conn):
            repo.upsert_orders_batch(self._conn, self._orders)
            repo.upsert_attempts_batch(self._conn, self._attempts)
            repo.insert_truth_attempts_batch(self._conn, self._truths)
        self._orders.clear()
        self._attempts.clear()
        self._truths.clear()
