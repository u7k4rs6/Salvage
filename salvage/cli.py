"""Salvage command line interface.

argparse, not typer or click: Architecture section 14 fixes the dependency set and does not list a
CLI library. Commands, per Architecture section 14 and the M1 brief:

  salvage db migrate
  salvage sim run --scenario S1 --seed 1
  salvage detect calibrate --seeds 0..4
  salvage ledger verify
  salvage ledger export --out data/ledger.jsonl
  salvage webhooks record --out data/webhooks
  salvage webhooks replay <dir>
  salvage serve
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from salvage.config import ConfigError, get_settings
from salvage.db import migrate, open_migrated
from salvage.ledger import export_jsonl, verify


def _db_path(args: argparse.Namespace) -> Path | None:
    return Path(args.db) if getattr(args, "db", None) else None


# ---------------------------------------------------------------------------
# db
# ---------------------------------------------------------------------------


def cmd_db_migrate(args: argparse.Namespace) -> int:
    from salvage.db import connect

    conn = connect(_db_path(args))
    applied = migrate(conn)
    path = args.db or get_settings().salvage_db_path
    if applied:
        print(f"Applied {len(applied)} migration(s) to {path}: {', '.join(applied)}")
    else:
        print(f"Schema already up to date at {path}")
    conn.close()
    return 0


# ---------------------------------------------------------------------------
# ledger
# ---------------------------------------------------------------------------


def cmd_ledger_verify(args: argparse.Namespace) -> int:
    conn = open_migrated(_db_path(args))
    result = verify(conn)
    conn.close()
    print(result)
    return 0 if result.ok else 1


def cmd_ledger_export(args: argparse.Namespace) -> int:
    conn = open_migrated(_db_path(args))
    written = export_jsonl(conn, args.out)
    conn.close()
    print(f"Exported {written} entries to {args.out}")
    print(f"Verify offline with: python3 scripts/verify_ledger.py {args.out}")
    return 0


# ---------------------------------------------------------------------------
# sim
# ---------------------------------------------------------------------------


def cmd_sim_run(args: argparse.Namespace) -> int:
    from salvage.detect.run import detect
    from salvage.sim.runner import run_scenario

    conn = open_migrated(_db_path(args))
    try:
        result = run_scenario(conn, scenario=args.scenario, seed=args.seed, days=args.days)
        print(
            f"run_id={result.run_id} scenario={result.scenario} seed={result.seed}\n"
            f"attempts={result.attempts} failures={result.failures} orders={result.orders} "
            f"customers={result.customers}\n"
            f"ground_truth_rows={result.truth_rows} sim window={result.sim_start}..{result.sim_end}"
        )
        if args.detect:
            eval_days = max(1, (result.sim_end - result.eval_day_start) // 86400 + 1)
            report = detect(
                conn,
                eval_start=result.eval_day_start,
                eval_end=result.eval_day_start + eval_days * 86400,
            )
            print(
                f"detector: {report.windows_evaluated} windows, "
                f"{report.incidents_opened} incident(s) opened, "
                f"{len(report.closed)} closed, {report.stats_written} segment stats"
            )
            for opened in report.opened:
                offset = ""
                if result.scheduled_faults:
                    minutes = (opened.opened_at - result.scheduled_faults[0].start_ts) / 60
                    offset = f", {minutes:.0f} sim minutes after fault onset"
                print(f"  {opened.incident_id} on {opened.segment_key}{offset}")
    finally:
        conn.close()
    return 0


# ---------------------------------------------------------------------------
# detect
# ---------------------------------------------------------------------------


def _parse_seeds(spec: str) -> list[int]:
    """Accepts '0..4' and '0,1,2'."""
    spec = spec.strip()
    if ".." in spec:
        lo, _, hi = spec.partition("..")
        return list(range(int(lo), int(hi) + 1))
    return [int(part) for part in spec.split(",") if part.strip()]


def cmd_detect_calibrate(args: argparse.Namespace) -> int:
    from salvage.detect.calibrate import calibrate, format_table

    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    rows = calibrate(scenarios=scenarios, seeds=_parse_seeds(args.seeds), days=args.days)
    print(format_table(rows))
    return 0


# ---------------------------------------------------------------------------
# webhooks
# ---------------------------------------------------------------------------


def cmd_webhooks_record(args: argparse.Namespace) -> int:
    from salvage.ingest.replay import record_verified_events

    conn = open_migrated(_db_path(args))
    written = record_verified_events(conn, args.out)
    conn.close()
    print(f"Wrote {written} verified event(s) to {args.out}")
    return 0


def cmd_webhooks_replay(args: argparse.Namespace) -> int:
    from salvage.ingest.replay import ReplayRefused, replay_directory

    conn = open_migrated(_db_path(args))
    try:
        summary = replay_directory(conn, args.directory)
    except ReplayRefused as exc:
        conn.close()
        print(f"replay refused: {exc}", file=sys.stderr)
        return 2
    conn.close()
    print(
        f"Replayed {summary.replayed} event(s), {summary.duplicates} duplicate(s), "
        f"{summary.skipped} skipped"
    )
    return 0


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("salvage.api.app:app", host=args.host, port=args.port, reload=False)
    return 0


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="salvage", description="Salvage command line interface.")
    parser.add_argument("--db", help="database path, overrides SALVAGE_DB_PATH")
    subparsers = parser.add_subparsers(dest="group", required=True)

    db = subparsers.add_parser("db", help="database maintenance").add_subparsers(
        dest="command", required=True
    )
    db.add_parser("migrate", help="apply pending migrations").set_defaults(func=cmd_db_migrate)

    ledger = subparsers.add_parser("ledger", help="audit ledger").add_subparsers(
        dest="command", required=True
    )
    ledger.add_parser("verify", help="recompute the hash chain").set_defaults(
        func=cmd_ledger_verify
    )
    export = ledger.add_parser("export", help="write the chain as JSONL")
    export.add_argument("--out", default="data/ledger.jsonl", help="output path")
    export.set_defaults(func=cmd_ledger_export)

    sim = subparsers.add_parser("sim", help="simulator").add_subparsers(
        dest="command", required=True
    )
    sim_run = sim.add_parser("run", help="run one scenario and write events and ground truth")
    sim_run.add_argument("--scenario", required=True, help="S0 to S4")
    sim_run.add_argument("--seed", type=int, required=True)
    sim_run.add_argument(
        "--days", type=int, default=None, help="evaluation days, default from params.yaml"
    )
    # The detector runs by default. The architecture is one pipeline: a database with traffic and
    # no incidents is not a state any other part of Salvage can use.
    sim_run.add_argument(
        "--no-detect",
        dest="detect",
        action="store_false",
        help="generate traffic only, do not run the detector",
    )
    sim_run.set_defaults(func=cmd_sim_run, detect=True)

    detect = subparsers.add_parser("detect", help="detector").add_subparsers(
        dest="command", required=True
    )
    calibrate = detect.add_parser("calibrate", help="run scenarios and print the calibration table")
    calibrate.add_argument("--seeds", default="0..4", help="'0..4' or '0,1,2'")
    calibrate.add_argument("--scenarios", default="S0,S1,S2,S3,S4")
    calibrate.add_argument("--days", type=int, default=None)
    calibrate.set_defaults(func=cmd_detect_calibrate)

    webhooks = subparsers.add_parser("webhooks", help="webhook capture and replay").add_subparsers(
        dest="command", required=True
    )
    record = webhooks.add_parser("record", help="write verified raw events to disk")
    record.add_argument("--out", default="data/webhooks", help="output directory")
    record.set_defaults(func=cmd_webhooks_record)
    replay = webhooks.add_parser("replay", help="feed recorded events back through the normaliser")
    replay.add_argument("directory", help="directory written by 'webhooks record'")
    replay.set_defaults(func=cmd_webhooks_replay)

    serve = subparsers.add_parser("serve", help="run the FastAPI app on loopback")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
