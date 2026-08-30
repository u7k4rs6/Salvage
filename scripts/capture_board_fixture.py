#!/usr/bin/env python3
"""Capture `GET /api/overview` from a world stopped mid-incident, at the evening peak.

Why this exists. The simulator is a batch: `run_scenario` writes every attempt of the day before
the detector sees any of them, and `POST /api/sim/run` then detects, acts and settles in one
thread with no interruption point. `SimRequest.speed` is accepted and never read. So there is no
moment at which the running system holds a mid-run database, and by the time any run returns, the
incident has closed. A capture taken afterwards has `incidents: []` and `at_risk_amount: 0`, which
is what the first board fixture had, and it reads as a broken payload rather than as a settled
world.

What this does instead is build a world that genuinely stops at a chosen sim minute:

  1. simulate the whole day, which is the only mode the simulator has
  2. delete everything after T, so the database has no future, the way a real one at time T does
  3. detect over [day start, T), which opens the incident and never reaches the windows that
     would close it
  4. run the policy with `until=T`, so no case, action or organic route exists past T
  5. call the overview route in process and write what it returns

Step 2 has to come before steps 3 and 4 or the agent snapshots the whole day's organic recoveries
at once. Step 2 is also the only step that touches data the simulator wrote, so it is the one to
distrust: the ledger still carries entries for orders that no longer exist, and the fixture's
`_note` says so. Nothing here is a source for a number in `docs/RESULTS.md`, which is measured by
`salvage eval run` over complete worlds.

The default stop is 20:45 IST, seventy five minutes into S1's fault. The fault runs 19:30 to
21:00, the diurnal weight over that hour is 2.45 against a mean of 1.029, and the incident has
been open for about an hour by then.

    uv run python3 scripts/capture_board_fixture.py
    uv run python3 scripts/capture_board_fixture.py --scenario S1 --seed 1 --at-minute 1245
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from salvage.api.routes_incidents import incident_detail, overview  # noqa: E402
from salvage.db import open_migrated  # noqa: E402
from salvage.detect.run import detect  # noqa: E402
from salvage.eval.baselines import get_policy  # noqa: E402
from salvage.execute.scheduler import AgentRunner, SimulatedLinkGateway  # noqa: E402
from salvage.sim.params import default_params  # noqa: E402
from salvage.sim.response import ResponseModel  # noqa: E402
from salvage.sim.runner import run_scenario  # noqa: E402


def trim_future(conn, cutoff: int) -> dict[str, int]:
    """Delete everything the simulator wrote at or after `cutoff`.

    A database at time T has no rows dated after T. Without this the overview route reports the
    rest of the day in `attempts_last_hour` and in the sparkline, because both queries are open
    ended above: `WHERE created_at >= ?` with no upper bound.
    """
    counts: dict[str, int] = {}
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.execute(
            "DELETE FROM sim_truth_attempts WHERE attempt_id IN "
            "(SELECT id FROM payment_attempts WHERE created_at >= ?)",
            (cutoff,),
        )
        counts["sim_truth_attempts"] = cur.rowcount
        cur = conn.execute("DELETE FROM payment_attempts WHERE created_at >= ?", (cutoff,))
        counts["payment_attempts"] = cur.rowcount
        cur = conn.execute("DELETE FROM orders WHERE created_at >= ?", (cutoff,))
        counts["orders"] = cur.rowcount
        # An order paid after the cutoff is not yet paid at the cutoff.
        cur = conn.execute(
            "UPDATE orders SET paid_at = NULL WHERE paid_at IS NOT NULL AND paid_at >= ?",
            (cutoff,),
        )
        counts["orders_unpaid"] = cur.rowcount
        conn.execute(
            "UPDATE orders SET status = CASE "
            "  WHEN paid_at IS NOT NULL THEN 'paid' "
            "  WHEN EXISTS (SELECT 1 FROM payment_attempts a WHERE a.order_id = orders.id) "
            "    THEN 'attempted' "
            "  ELSE 'created' END"
        )
        cur = conn.execute(
            "UPDATE customers SET opted_out_at = NULL "
            "WHERE opted_out_at IS NOT NULL AND opted_out_at >= ?",
            (cutoff,),
        )
        counts["customers_opt_in"] = cur.rowcount
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return counts


def build_provider(policy: str):
    """The recorded fixtures, or nothing. Never a live call from a capture script."""
    if policy != "agent":
        return None
    from salvage.llm.provider import FIXTURE_DIR, FixtureProvider

    if not list(FIXTURE_DIR.glob("*.json")):
        return None
    return FixtureProvider(FIXTURE_DIR, strict=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", default="S1")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--policy", default="agent", choices=["agent", "B0", "B1", "B2", "echo"])
    parser.add_argument("--variant", default="peak", choices=["peak", "offpeak"])
    parser.add_argument(
        "--at-minute",
        type=int,
        default=1245,
        help="sim minute of the evaluation day to stop at, IST. Default 1245 is 20:45.",
    )
    parser.add_argument("--db", default="", help="database file, default a temporary one")
    parser.add_argument(
        "--no-trim",
        action="store_true",
        help="skip step 2, leaving the simulator's future rows in place. Only useful for "
        "showing what the future does to a number computed before it happened.",
    )
    parser.add_argument("--out", default="web/src/board/fixtures/s1_detected.json")
    args = parser.parse_args(argv)

    # Not beside the fixture. The working database is a hundred megabytes of simulated world and
    # the fixture is sixty kilobytes of JSON; putting them in the same directory is how the first
    # run left a 109 MB file inside web/src.
    if args.db:
        db_path = Path(args.db)
    else:
        db_path = Path(tempfile.gettempdir()) / f"salvage_board_{args.scenario}_{args.seed}.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        Path(str(db_path) + suffix).unlink(missing_ok=True)

    conn = open_migrated(db_path)
    params = default_params()

    print(f"simulating {args.scenario} seed {args.seed} variant {args.variant}")
    sim = run_scenario(conn, scenario=args.scenario, seed=args.seed, variant=args.variant)
    day_start = sim.eval_day_start
    cutoff = day_start + args.at_minute * 60
    hhmm = f"{args.at_minute // 60:02d}:{args.at_minute % 60:02d}"
    print(
        f"  {sim.attempts} attempts over the run, "
        f"stopping at sim minute {args.at_minute} ({hhmm} IST)"
    )

    for fault in sim.scheduled_faults:
        inside = "open" if fault.start_ts <= cutoff < fault.end_ts else "not active"
        print(f"  fault {dict(fault.fault.selector)} {inside} at the cutoff")

    if args.no_trim:
        print("  NOT trimming the future, per --no-trim")
    else:
        removed = trim_future(conn, cutoff)
        print(f"  trimmed the future: {removed}")

    print("detecting")
    report = detect(conn, eval_start=day_start, eval_end=cutoff)
    print(
        f"  {report.incidents_opened} incident(s) opened, {len(report.closed)} closed, "
        f"{report.windows_evaluated} windows evaluated, {report.stats_written} stats rows"
    )

    provider = build_provider(args.policy)
    print(f"running policy {args.policy}, provider {getattr(provider, 'name', 'none')}")
    runner = AgentRunner(
        conn,
        response=ResponseModel(params, args.seed),
        provider=provider if get_policy(args.policy).diagnoses else None,
        gateway=SimulatedLinkGateway(),
        kill_switch=False,
        profile=get_policy(args.policy),
        seed=args.seed,
        world_faults=[
            {"start": f.start_ts, "end": f.end_ts, "selector": dict(f.fault.selector)}
            for f in sim.scheduled_faults
        ],
        escalation_fix_minutes=params.escalation_fix_minutes,
    )
    stats = runner.run(until=cutoff, window_start=day_start, window_end=cutoff)
    print(f"  {stats.actions_executed} action(s) executed, {stats.actions_refused} refused")
    if provider is not None and getattr(provider, "misses", []):
        print(f"  WARNING: {len(provider.misses)} fixture miss(es); the diagnosis is not recorded")

    payload = overview(lambda: conn)
    open_ids = [entry["id"] for entry in payload["incidents"]]
    print(
        f"captured: {len(payload['segments'])} segments, {len(payload['incidents'])} open "
        f"incident(s), {len(payload['series'])} series points"
    )

    document = {
        "_note": (
            f"GET /api/overview from {args.scenario} seed {args.seed} variant {args.variant}, "
            f"policy {args.policy}, captured at sim minute {args.at_minute} ({hhmm} IST) with the "
            "incident open. Whole arrays, nothing truncated. Produced by "
            "scripts/capture_board_fixture.py, which stops the world at the cutoff by deleting "
            "every simulator row dated at or after it. The ledger still references orders that "
            "were deleted, so this database is a board fixture and not an evaluation input. No "
            "number in docs/RESULTS.md comes from here."
        ),
        "_captured_at_sim_minute": args.at_minute,
        "_cutoff_unix": cutoff,
        "GET /api/overview": payload,
    }
    if open_ids:
        document["GET /api/incidents/{id}"] = incident_detail(open_ids[0], lambda: conn)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
