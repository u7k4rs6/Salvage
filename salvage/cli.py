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
import json
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
        result = run_scenario(
            conn,
            scenario=args.scenario,
            seed=args.seed,
            days=args.days,
            variant=args.variant,
        )
        print(
            f"run_id={result.run_id} scenario={result.scenario} seed={result.seed} "
            f"variant={result.variant}\n"
            f"attempts={result.attempts} (first {result.first_attempts}, "
            f"organic retries {result.retries}) failures={result.failures}\n"
            f"orders={result.orders} paid={result.orders_paid} "
            f"(paid on an organic retry: {result.orders_paid_on_retry}) "
            f"customers={result.customers}\n"
            f"ground_truth_rows={result.truth_rows} "
            f"sim window={result.sim_start}..{result.sim_end}\n"
            f"stream_digest={result.stream_digest[:16]} "
            f"dropped_retries={result.dropped_retries}"
        )
        if args.detect:
            # The evaluation days only. The settlement tail creates no new orders, so running the
            # detector over it would evaluate three days of traffic that does not exist and
            # inflate the window count in every report.
            from salvage.sim.params import default_params

            eval_days = args.days if args.days is not None else default_params().eval_days
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


def cmd_sim_verify_stream(args: argparse.Namespace) -> int:
    from salvage.sim.verify import StreamNotCommitted, verify_stream

    conn = open_migrated(_db_path(args))
    try:
        result = verify_stream(conn, args.run_id)
    except StreamNotCommitted as exc:
        print(f"stream not committed: {exc}", file=sys.stderr)
        return 2
    finally:
        conn.close()
    print(result)
    return 0 if result.ok else 1


def cmd_sim_organic(args: argparse.Namespace) -> int:
    """Organic-only recovery, which is baseline B0. Runs each scenario into its own database."""
    import shutil

    from salvage.detect.calibrate import make_workdir
    from salvage.eval.baselines import format_organic_table, measure_organic_recovery
    from salvage.sim.runner import run_scenario

    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    seeds = _parse_seeds(args.seeds)
    workdir = make_workdir()
    rows = []
    try:
        for scenario in scenarios:
            for seed in seeds:
                db_path = workdir / f"{scenario}_{seed}_{args.variant}.db"
                conn = open_migrated(db_path)
                try:
                    result = run_scenario(conn, scenario=scenario, seed=seed, variant=args.variant)
                    rows.append(
                        measure_organic_recovery(
                            conn,
                            scenario=scenario,
                            seed=seed,
                            variant=args.variant,
                            fault_windows=[(f.start_ts, f.end_ts) for f in result.scheduled_faults],
                        )
                    )
                finally:
                    conn.close()
                    for suffix in ("", "-wal", "-shm"):
                        Path(str(db_path) + suffix).unlink(missing_ok=True)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    print(format_organic_table(rows))
    return 0


def cmd_detect_calibrate(args: argparse.Namespace) -> int:
    from salvage.detect.calibrate import calibrate, format_table

    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    rows = calibrate(
        scenarios=scenarios,
        seeds=_parse_seeds(args.seeds),
        days=args.days,
        variant=args.variant,
    )
    print(format_table(rows))
    return 0


# ---------------------------------------------------------------------------
# agent
# ---------------------------------------------------------------------------


def _make_provider(args: argparse.Namespace):
    """The provider named on the command line, or None for the model-free path."""
    if args.provider == "none":
        return None
    from salvage.llm.provider import build_provider

    if args.provider in ("collect", "fixture-collect"):
        return build_provider(args.provider, out_path=args.collect_out)
    return build_provider(args.provider)


def cmd_agent_run(args: argparse.Namespace) -> int:
    from salvage.eval.agent_run import run_agent_scenario

    provider = _make_provider(args)

    conn = open_migrated(_db_path(args))
    try:
        result = run_agent_scenario(
            conn,
            scenario=args.scenario,
            seed=args.seed,
            variant=args.variant,
            provider=provider,
            kill_switch=args.kill_switch,
        )
    finally:
        conn.close()

    stats = result.stats
    print(
        f"run_id={result.sim.run_id} scenario={args.scenario} seed={args.seed} "
        f"variant={args.variant}\n"
        f"incidents={stats.incidents} diagnosed={stats.diagnosed} "
        f"escalations={stats.escalations}\n"
        f"cases={stats.cases} actions proposed={stats.actions_proposed} "
        f"executed={stats.actions_executed} refused={stats.actions_refused} "
        f"deferred={stats.actions_deferred} queued={stats.actions_queued}\n"
        f"links={stats.links_created} messages sent={stats.messages_sent} "
        f"rejected by validator={stats.messages_rejected} opt-outs={stats.opt_outs}\n"
        f"recovered by the agent: {stats.recovered_cases} case(s), "
        f"{stats.recovered_amount} paise\n"
        f"organic recovery (B0) in the same run: {result.organic.recovered_orders}/"
        f"{result.organic.failed_orders} orders "
        f"({result.organic.recovery_rate:.3f})"
    )
    for incident in result.incidents:
        print(
            f"  incident {incident['id']} on {incident['segment_key']}: "
            f"rules={incident['rules_cause']} llm={incident['llm_cause']} "
            f"cause={incident['root_cause']} confidence={incident['confidence']}"
        )
    for escalation in result.escalations:
        print(f"  escalation {escalation['id']}: {escalation['reason']}")
    return 0


# ---------------------------------------------------------------------------
# diagnose
# ---------------------------------------------------------------------------


def cmd_diagnose_accuracy(args: argparse.Namespace) -> int:
    from salvage.eval.metrics import format_accuracy_table, summarise
    from salvage.eval.run import diagnosis_sweep

    provider = _make_provider(args)

    outcomes = diagnosis_sweep(
        scenarios=[s.strip() for s in args.scenarios.split(",") if s.strip()],
        seeds=_parse_seeds(args.seeds),
        variant=args.variant,
        provider=provider,
    )
    print(format_accuracy_table(summarise(outcomes), outcomes))
    return 0


def cmd_diagnose_export_prompts(args: argparse.Namespace) -> int:
    import json as _json

    from salvage.eval.run import export_prompts

    rows = export_prompts(
        scenarios=[s.strip() for s in args.scenarios.split(",") if s.strip()],
        seeds=_parse_seeds(args.seeds),
        variant=args.variant,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(_json.dumps(row, sort_keys=True) + "\n")
    print(f"Wrote {len(rows)} prompt(s) to {out}")
    return 0


def cmd_diagnose_import_fixtures(args: argparse.Namespace) -> int:
    """Write fixture files from a hand-authored or externally produced answer set.

    The answers file is JSON: a mapping of prompt_hash to the LLMDiagnosis object. Every answer is
    validated against the schema before it is written, so an invalid fixture cannot enter the set.
    """
    import json as _json

    from salvage.decide.planner import Plan
    from salvage.diagnose.llm import LLMDiagnosis
    from salvage.llm.provider import FIXTURE_DIR, write_fixture

    # The schema an answer is validated against is the one the prompt asked for. A planner answer
    # validated against the diagnosis schema would be rejected for the wrong reason.
    schemas = {"LLMDiagnosis": LLMDiagnosis, "Plan": Plan}

    prompts = {}
    with Path(args.prompts).open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                row = _json.loads(line)
                prompts[row["prompt_hash"]] = row

    answers = _json.loads(Path(args.answers).read_text(encoding="utf-8"))
    directory = Path(args.out or FIXTURE_DIR)
    written = 0
    for key, answer in answers.items():
        if key not in prompts:
            print(f"no prompt for hash {key}, skipping", file=sys.stderr)
            continue
        schema_name = prompts[key].get("schema_title", "LLMDiagnosis")
        schema = schemas.get(schema_name)
        if schema is None:
            print(f"unknown schema {schema_name!r} for hash {key}, skipping", file=sys.stderr)
            continue
        validated = schema.model_validate(answer)
        write_fixture(
            directory,
            key=key,
            system=prompts[key]["system"],
            user=prompts[key]["user"],
            response=json.loads(validated.model_dump_json()),
            recorded_from=args.recorded_from,
            model=args.model,
        )
        written += 1
    print(f"Wrote {written} fixture(s) to {directory}")
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
    sim_run.add_argument(
        "--variant",
        default="peak",
        help="fault variant from params.yaml: peak (default) or offpeak",
    )
    sim_run.set_defaults(func=cmd_sim_run, detect=True)

    verify_stream = sim.add_parser(
        "verify-stream", help="recompute the ledger's commitment to the attempt stream"
    )
    verify_stream.add_argument(
        "run_id", nargs="?", default=None, help="defaults to the most recent run"
    )
    verify_stream.set_defaults(func=cmd_sim_verify_stream)

    organic = sim.add_parser(
        "organic", help="organic-only recovery rate per scenario, which is baseline B0"
    )
    organic.add_argument("--scenarios", default="S0,S1,S2,S3,S4")
    organic.add_argument("--seeds", default="0..4", help="'0..4' or '0,1,2'")
    organic.add_argument("--variant", default="peak")
    organic.set_defaults(func=cmd_sim_organic)

    detect = subparsers.add_parser("detect", help="detector").add_subparsers(
        dest="command", required=True
    )
    calibrate = detect.add_parser("calibrate", help="run scenarios and print the calibration table")
    calibrate.add_argument("--seeds", default="0..4", help="'0..4' or '0,1,2'")
    calibrate.add_argument("--scenarios", default="S0,S1,S2,S3,S4")
    calibrate.add_argument("--days", type=int, default=None)
    calibrate.add_argument(
        "--variant",
        default="peak",
        help="fault variant from params.yaml: peak (default) or offpeak",
    )
    calibrate.set_defaults(func=cmd_detect_calibrate)

    agent = subparsers.add_parser("agent", help="the whole loop").add_subparsers(
        dest="command", required=True
    )
    agent_run = agent.add_parser(
        "run", help="simulate, detect, diagnose, plan, gate, act and settle one scenario"
    )
    agent_run.add_argument("--scenario", required=True)
    agent_run.add_argument("--seed", type=int, required=True)
    agent_run.add_argument("--variant", default="peak")
    agent_run.add_argument(
        "--provider",
        default="none",
        help="none, fixture, gemini, ollama, or collect to record prompts without answering",
    )
    agent_run.add_argument(
        "--collect-out",
        dest="collect_out",
        default="data/prompts_agent.jsonl",
        help="where the collect provider writes prompts",
    )
    agent_run.add_argument("--kill-switch", dest="kill_switch", action="store_true")
    agent_run.set_defaults(func=cmd_agent_run)

    diagnose = subparsers.add_parser("diagnose", help="diagnosis").add_subparsers(
        dest="command", required=True
    )
    accuracy = diagnose.add_parser(
        "accuracy", help="root-cause accuracy, rules-only and LLM-assisted, against ground truth"
    )
    accuracy.add_argument("--scenarios", default="S1,S2,S3,S4")
    accuracy.add_argument("--seeds", default="0..4", help="'0..4' or '0,1,2'")
    accuracy.add_argument("--variant", default="peak")
    accuracy.add_argument(
        "--provider",
        default="none",
        help="none for the rules-only floor, or fixture, gemini, ollama, collect",
    )
    accuracy.add_argument(
        "--collect-out", dest="collect_out", default="data/prompts_diagnose.jsonl"
    )
    accuracy.set_defaults(func=cmd_diagnose_accuracy)

    export = diagnose.add_parser(
        "export-prompts", help="write every diagnosis prompt the sweep would produce, with hashes"
    )
    export.add_argument("--scenarios", default="S1,S2,S3,S4")
    export.add_argument("--seeds", default="0..4")
    export.add_argument("--variant", default="peak")
    export.add_argument("--out", default="data/prompts.jsonl")
    export.set_defaults(func=cmd_diagnose_export_prompts)

    fixtures = diagnose.add_parser(
        "import-fixtures", help="write fixture files from an answer set keyed by prompt hash"
    )
    fixtures.add_argument("prompts", help="the JSONL written by export-prompts")
    fixtures.add_argument("answers", help="JSON mapping prompt_hash to an LLMDiagnosis object")
    fixtures.add_argument("--out", default=None, help="defaults to salvage/llm/fixtures/")
    fixtures.add_argument(
        "--recorded-from",
        dest="recorded_from",
        required=True,
        help="what produced these answers, recorded in every fixture file",
    )
    fixtures.add_argument("--model", required=True, help="the model id that produced them")
    fixtures.set_defaults(func=cmd_diagnose_import_fixtures)

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
