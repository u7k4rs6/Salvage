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
    """Organic-only recovery, which is exactly the B0 policy arm.

    Kept as its own command because it answers one question on its own: does anybody come back
    unprompted. If this is zero, every comparison against B0 is meaningless.
    """
    import shutil

    from salvage.detect.calibrate import make_workdir
    from salvage.eval.agent_run import run_policy_scenario
    from salvage.eval.metrics import format_metrics_table

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
                    result = run_policy_scenario(
                        conn,
                        scenario=scenario,
                        seed=seed,
                        policy="B0",
                        variant=args.variant,
                    )
                    rows.append(result.metrics)
                finally:
                    conn.close()
                    for suffix in ("", "-wal", "-shm"):
                        Path(str(db_path) + suffix).unlink(missing_ok=True)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    print(format_metrics_table(rows, title="Organic-only recovery (policy B0)"))
    zero = [row.scenario for row in rows if row.recovered_orders == 0]
    if zero:
        print()
        print(
            "WARNING: organic recovery is zero for "
            + ", ".join(sorted(set(zero)))
            + ". B0 recovers nothing there, so any comparison against it is meaningless."
        )
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
    from salvage.eval.agent_run import run_policy_scenario

    provider = _make_provider(args)

    conn = open_migrated(_db_path(args))
    try:
        result = run_policy_scenario(
            conn,
            scenario=args.scenario,
            seed=args.seed,
            policy=args.policy,
            variant=args.variant,
            provider=provider,
            kill_switch=args.kill_switch,
        )
    finally:
        conn.close()

    stats = result.stats
    metrics = result.metrics
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
        f"eligible orders {metrics.eligible_orders} worth {metrics.eligible_amount} paise\n"
        f"RECOVERED (all routes) {metrics.recovered_orders} order(s), "
        f"{metrics.recovered_amount} paise, rate {metrics.recovery_rate:.3f}\n"
        f"  by route: "
        + ", ".join(
            f"{route}={metrics.by_route_orders.get(route, 0)}"
            f"/{metrics.by_route_amount.get(route, 0)}p"
            for route in ("link", "steer", "organic")
        )
        + "\n"
        f"at risk: {metrics.at_risk_recovered_orders}/{metrics.at_risk_orders} "
        f"({metrics.at_risk_recovery_rate:.3f}), {metrics.at_risk_messages} message(s) to "
        f"at-risk customers, {metrics.opt_outs} opt-out(s)\n"
        f"policy violations: {metrics.policy_violations}   "
        f"stream_digest={metrics.stream_digest[:16]}"
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

    seeds = _parse_seeds(args.seeds)
    outcomes = diagnosis_sweep(
        scenarios=[s.strip() for s in args.scenarios.split(",") if s.strip()],
        seeds=seeds,
        variant=args.variant,
        provider=provider,
    )
    rows = summarise(outcomes)
    print(format_accuracy_table(rows, outcomes))

    # Written so docs/RESULTS.md can carry the table with its provenance rather than a claim.
    provenance = (
        "Rules-only. The LLM column is unmeasured: the fixtures M2 shipped were written by the "
        "model being evaluated, with the scenario labels visible, and were deleted in M3. See "
        "salvage/llm/fixtures/README.md."
        if args.provider == "none"
        else f"Rules-only against the {args.provider} provider."
    )
    _write_artifact(
        "diagnosis.json",
        {
            "provenance": provenance,
            "provider": args.provider,
            "seeds": seeds,
            "rows": [
                {
                    "scenario": row.scenario,
                    "incidents": row.incidents,
                    "seeds": len(seeds),
                    "rules_accuracy": row.rules_accuracy,
                    "llm_accuracy": (
                        f"{row.llm_accuracy:.2f}" if row.llm_accuracy is not None else "unmeasured"
                    ),
                }
                for row in rows
            ],
            "misses": [
                f"{o.scenario} seed {o.seed} on `{o.segment_key}`: truth {o.true_cause}, "
                f"rules said {o.rules_cause}"
                for o in outcomes
                if not o.rules_correct
            ],
        },
    )
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


def cmd_diagnose_record_fixtures(args: argparse.Namespace) -> int:
    """Record diagnosis fixtures from a live provider, blind to the scenario labels."""
    from salvage.eval.run import LabelLeak, prompts_for_recording, record_fixtures
    from salvage.llm.provider import build_provider

    if args.provider not in ("gemini", "ollama"):
        print(
            "fixtures must be recorded from a live provider: --provider gemini or ollama",
            file=sys.stderr,
        )
        return 2

    provider = build_provider(args.provider)
    try:
        prompts = prompts_for_recording(
            scenarios=[s.strip() for s in args.scenarios.split(",") if s.strip()],
            seeds=_parse_seeds(args.seeds),
            variant=args.variant,
        )
    except LabelLeak as exc:
        print(f"refusing to record: {exc}", file=sys.stderr)
        return 2

    written, failures = record_fixtures(prompts, provider, directory=args.out)
    print(f"Recorded {written} fixture(s) from {provider.name} model {provider.model}")
    for failure in failures:
        print(f"  failed: {failure}", file=sys.stderr)
    if failures:
        print(f"{len(failures)} prompt(s) failed, see above", file=sys.stderr)
    return 0 if written else 1


# ---------------------------------------------------------------------------
# eval
# ---------------------------------------------------------------------------


def cmd_eval_run(args: argparse.Namespace) -> int:
    from salvage.eval.metrics import format_metrics_table
    from salvage.eval.sweep import (
        aggregate,
        digests_match,
        sweep,
        write_results_json,
    )

    provider = _make_provider(args)
    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    policies = [p.strip() for p in args.policies.split(",") if p.strip()]
    seeds = _parse_seeds(args.seeds)

    total = len(scenarios) * len(seeds) * len(policies)
    print(
        f"Running {total} combination(s): {len(scenarios)} scenario(s) x "
        f"{len(seeds)} seed(s) x {len(policies)} policy arm(s), variant {args.variant}"
    )

    def progress(done, total_runs, scenario, seed, policy, metrics):
        print(
            f"  [{done:>4}/{total_runs}] {scenario}/{seed}/{policy}: "
            f"recovered {metrics.recovered_orders}/{metrics.eligible_orders} "
            f"({metrics.recovered_amount} paise), {metrics.messages_sent} message(s), "
            f"{metrics.policy_violations} violation(s)",
            flush=True,
        )

    result = sweep(
        scenarios=scenarios,
        seeds=seeds,
        policies=policies,
        variant=args.variant,
        provider=provider,
        run_id=args.run_id,
        progress=progress if args.verbose else None,
    )

    path = write_results_json(result)
    print()
    print(format_metrics_table(result.rows, title="Per-run metrics"))
    print()
    print(_digest_block(result))
    print()
    print(_aggregate_block(aggregate(result.rows)))
    print()
    print(f"Wrote {path} in {result.wall_seconds}s")
    for note in result.notes:
        print(note, file=sys.stderr)

    if args.write_report:
        from salvage.eval.report import write_results_md

        report_path = write_results_md(result)
        print(f"Wrote {report_path}")

    return 0 if digests_match(result) else 1


def _digest_block(result) -> str:
    """The identical-world proof, printed so the report can show them matching."""
    lines = ["Pre-intervention attempt stream digest, per scenario and seed:"]
    header = f"  {'scenario/seed':<16}" + "".join(f"{p:>18}" for p in result.policies) + "  match"
    lines.append(header)
    for key in sorted(result.digests):
        digests = result.digests[key]
        row = f"  {key:<16}" + "".join(
            f"{digests.get(policy, '')[:16]:>18}" for policy in result.policies
        )
        match = "yes" if len(set(digests.values())) <= 1 else "NO"
        lines.append(f"{row}  {match}")
    return "\n".join(lines)


def _aggregate_block(rows) -> str:
    header = (
        f"{'scenario':<9}{'policy':>7}{'seeds':>7}{'recovered revenue (mean +/- sd)':>36}"
        f"{'rate':>7}{'in-fault':>10}{'msgs':>7}{'viol':>6}"
    )
    lines = ["Aggregated across seeds:", header, "-" * len(header)]
    for row in rows:
        summary = f"{row.mean_recovered_amount:,.0f} +/- {row.std_recovered_amount:,.0f}"
        lines.append(
            f"{row.scenario:<9}{row.policy:>7}{row.seeds:>7}{summary:>36}"
            f"{row.mean_recovery_rate:>7.3f}{row.mean_at_risk_recovery_rate:>10.3f}"
            f"{row.mean_messages:>7.0f}{row.total_violations:>6}"
        )
    return "\n".join(lines)


def cmd_eval_volume(args: argparse.Namespace) -> int:
    from salvage.eval.sweep import volume_sweep

    payload = volume_sweep(
        scenarios=[s.strip() for s in args.scenarios.split(",") if s.strip()],
        seeds=_parse_seeds(args.seeds),
        volumes=tuple(int(v) for v in args.volumes.split(",")),
        variant=args.variant,
    )
    _write_artifact("volume_sweep.json", payload)
    header = (
        f"{'attempts/day':>13}{'scenario':>10}{'seeds':>7}{'detected':>10}"
        f"{'<15 min':>9}{'mean min':>10}{'worst':>8}  segment"
    )
    print(header)
    print("-" * len(header))
    for row in payload["rows"]:
        mean = f"{row['mean_time_to_detect']:.1f}" if row["mean_time_to_detect"] else "n/a"
        worst = f"{row['worst_time_to_detect']:.0f}" if row["worst_time_to_detect"] else "n/a"
        print(
            f"{row['attempts_per_day']:>13,}{row['scenario']:>10}{row['seeds']:>7}"
            f"{row['detected']:>10}{row['within_15_minutes']:>9}{mean:>10}{worst:>8}  "
            f"{row['segments']}"
        )
    print()
    print(payload["boundary"])
    return 0


def cmd_eval_sensitivity(args: argparse.Namespace) -> int:
    from salvage.eval.sweep import adversarial_sweep, sensitivity_sweep

    payload = sensitivity_sweep(
        scenario=args.scenario,
        seeds=_parse_seeds(args.seeds),
        scales=tuple(float(v) for v in args.scales.split(",")),
    )
    if args.adversarial:
        payload["adversarial"] = adversarial_sweep(
            scenarios=[s.strip() for s in args.scenarios.split(",") if s.strip()],
            seeds=_parse_seeds(args.seeds),
        )
    _write_artifact("sensitivity.json", payload)

    print(f"Sensitivity on {payload['scenario']}, multiplier scale against recovered revenue")
    header = f"{'scale':>7}{'seeds':>7}{'B0 (paise)':>16}{'B1 (paise)':>16}{'B1 - B0':>16}"
    print(header)
    print("-" * len(header))
    for row in payload["rows"]:
        print(
            f"{row['scale']:>7.2f}{row['seeds']:>7}{row['b0']:>16,.0f}"
            f"{row['b1']:>16,.0f}{row['delta']:>16,.0f}"
        )
    if args.adversarial:
        print()
        print("Adversarial set: p_organic 0.60 everywhere, every multiplier 1.0")
        adv = payload["adversarial"]
        print(f"{'scenario':>10}{'seeds':>7}" + "".join(f"{p:>16}" for p in adv["policies"]))
        for row in adv["rows"]:
            cells = "".join(f"{row['by_policy'][p]:>16,.0f}" for p in adv["policies"])
            print(f"{row['scenario']:>10}{row['seeds']:>7}{cells}")
    return 0


def cmd_eval_report(args: argparse.Namespace) -> int:
    """Regenerate docs/RESULTS.md from the artifacts already on disk."""
    from salvage.eval.report import ReportInputs, load_json, rows_from_json, write_results_md

    main_payload = load_json(Path(args.results))
    if main_payload is None:
        print(f"no results file at {args.results}", file=sys.stderr)
        return 2
    offpeak_payload = load_json(Path(args.offpeak)) if args.offpeak else None
    inputs = ReportInputs(
        main=rows_from_json(main_payload),
        volume_sweep=load_json("data/results/volume_sweep.json"),
        offpeak=rows_from_json(offpeak_payload) if offpeak_payload else None,
        sensitivity=load_json("data/results/sensitivity.json"),
        diagnosis=load_json("data/results/diagnosis.json"),
        injection=load_json("data/results/fault_injection.json"),
    )
    path = write_results_md(inputs.main, inputs=inputs)
    print(f"Wrote {path}")

    from salvage.eval.sweep import write_metrics_csv

    csv_path = write_metrics_csv(inputs.main)
    print(f"Wrote {csv_path} ({len(inputs.main.rows)} rows)")
    return 0


def _write_artifact(name: str, payload) -> Path:
    import json as _json

    path = Path("data/results") / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# e2e
# ---------------------------------------------------------------------------


def cmd_e2e_verify(args: argparse.Namespace) -> int:
    """Check and print the ledger entries the real end-to-end run produced.

    scripts/e2e_real_link.py creates the real test-mode objects; this reads back what it recorded,
    verifies the chain, checks that the four entries the run must produce are present and linked
    to each other in order, and prints the sequence numbers and hashes in the shape
    docs/RESULTS.md section 11 wants.
    """
    from salvage.ledger import Ledger, verify

    conn = open_migrated(_db_path(args))
    try:
        required = ("e2e.order.created", "e2e.link.created", "e2e.link.paid")
        all_entries = Ledger(conn).entries()
        by_seq = {entry.seq: entry for entry in all_entries}
        e2e_entries = [entry for entry in all_entries if entry.kind in required]
        webhook_entries = [entry for entry in all_entries if entry.kind == "webhook.received"]
        result = verify(conn)

        if not e2e_entries:
            print(
                "No end-to-end ledger entries found. Run scripts/e2e_real_link.py first.",
                file=sys.stderr,
            )
            print(f"Ledger state: {result}", file=sys.stderr)
            return 1

        print("Real end-to-end run, ledger entries")
        print()
        header = f"{'seq':>5}  {'kind':<22} {'ref':<28} {'hash':<18} {'prev_hash':<18} detail"
        print(header)
        print("-" * len(header))
        for entry in e2e_entries + webhook_entries:
            payload = json.loads(entry.payload_json)
            detail = ", ".join(
                f"{key}={value}"
                for key, value in sorted(payload.items())
                if key
                in (
                    "order_id",
                    "link_id",
                    "payment_id",
                    "amount",
                    "request_id",
                    "event_type",
                    "verified",
                    "acted",
                )
            )
            print(
                f"{entry.seq:>5}  {entry.kind:<22} {entry.ref_id[:28]:<28} "
                f"{entry.hash[:16]:<18} {entry.prev_hash[:16]:<18} {detail}"
            )

        # Each entry must chain to the one before it. verify() already recomputes the whole chain;
        # this additionally shows the specific links a reviewer would check by eye.
        print()
        broken_links = []
        for entry in e2e_entries + webhook_entries:
            if entry.seq == 1:
                continue
            previous = by_seq.get(entry.seq - 1)
            if previous is None or previous.hash != entry.prev_hash:
                broken_links.append(entry.seq)
        if broken_links:
            print(f"Chain linkage broken at sequence {broken_links}", file=sys.stderr)
        else:
            print("Each entry's prev_hash matches the hash of the entry before it.")

        print(result)
        missing = [kind for kind in required if not any(e.kind == kind for e in e2e_entries)]
        if missing:
            print(f"Incomplete: no entry for {', '.join(missing)}", file=sys.stderr)
        if not webhook_entries:
            print(
                "No verified webhook was received. Point a tunnel at the webhook endpoint and "
                "run again, or replay a saved fixture with: salvage webhooks replay <dir>",
                file=sys.stderr,
            )

        print()
        print("Paste into docs/RESULTS.md section 11:")
        print()
        print("| field | value |")
        print("|---|---|")
        for kind, label in (
            ("e2e.order.created", "order id"),
            ("e2e.link.created", "payment link id"),
            ("e2e.link.paid", "payment id"),
        ):
            entry = next((e for e in e2e_entries if e.kind == kind), None)
            payload = json.loads(entry.payload_json) if entry else {}
            value = (
                payload.get("order_id")
                or payload.get("link_id")
                or payload.get("payment_id")
                or (entry.ref_id if entry else "not recorded")
            )
            print(f"| {label} | `{value}` |")
        events = ", ".join(f"`{entry.ref_id}`" for entry in webhook_entries) or "none received"
        print(f"| webhook event ids | {events} |")
        sequences = ", ".join(str(entry.seq) for entry in e2e_entries + webhook_entries)
        print(f"| ledger sequence numbers | {sequences} |")
        print(f"| head hash | `{result.head_hash}` |")

        return 0 if result.ok and not missing and not broken_links else 1
    finally:
        conn.close()


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
        "run", help="simulate, detect, run one policy, settle and measure one scenario"
    )
    agent_run.add_argument("--scenario", required=True)
    agent_run.add_argument("--seed", type=int, required=True)
    agent_run.add_argument("--policy", default="agent", help="agent, B0, B1 or B2")
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

    record = diagnose.add_parser(
        "record-fixtures",
        help="record diagnosis fixtures from a live provider, blind to the scenario labels",
    )
    record.add_argument("--scenarios", default="S1,S2,S3,S4")
    record.add_argument("--seeds", default="0..9")
    record.add_argument("--variant", default="peak")
    record.add_argument("--provider", default="gemini", help="gemini or ollama")
    record.add_argument("--out", default=None, help="defaults to salvage/llm/fixtures/")
    record.set_defaults(func=cmd_diagnose_record_fixtures)

    evaluation = subparsers.add_parser("eval", help="evaluation sweeps").add_subparsers(
        dest="command", required=True
    )
    eval_run = evaluation.add_parser(
        "run", help="run every scenario, seed and policy and write the results"
    )
    eval_run.add_argument("--scenarios", default="S0,S1,S2,S3,S4")
    eval_run.add_argument("--seeds", default="0..9", help="'0..9' or '0,1,2'")
    eval_run.add_argument("--policies", default="agent,B0,B1,B2")
    eval_run.add_argument("--variant", default="peak")
    eval_run.add_argument("--provider", default="none")
    eval_run.add_argument("--collect-out", dest="collect_out", default="data/prompts_eval.jsonl")
    eval_run.add_argument("--run-id", dest="run_id", default=None)
    eval_run.add_argument("--verbose", action="store_true", help="print each run as it finishes")
    eval_run.add_argument(
        "--write-report",
        dest="write_report",
        action="store_true",
        help="also write docs/RESULTS.md",
    )
    eval_run.set_defaults(func=cmd_eval_run)

    eval_volume = evaluation.add_parser(
        "volume", help="the same fault at several merchant volumes: the detector's envelope"
    )
    eval_volume.add_argument("--scenarios", default="S1,S2")
    eval_volume.add_argument("--seeds", default="0..4")
    eval_volume.add_argument("--volumes", default="1500,5000,12000")
    eval_volume.add_argument("--variant", default="peak")
    eval_volume.set_defaults(func=cmd_eval_volume)

    eval_sensitivity = evaluation.add_parser(
        "sensitivity", help="sweep the response-model multipliers and run the adversarial set"
    )
    eval_sensitivity.add_argument("--scenario", default="S1")
    eval_sensitivity.add_argument("--scenarios", default="S1,S2,S3")
    eval_sensitivity.add_argument("--seeds", default="0..4")
    eval_sensitivity.add_argument("--scales", default="0.5,0.75,1.0,1.5,2.0")
    eval_sensitivity.add_argument("--adversarial", action="store_true")
    eval_sensitivity.set_defaults(func=cmd_eval_sensitivity)

    eval_report = evaluation.add_parser(
        "report", help="regenerate docs/RESULTS.md from the artifacts on disk"
    )
    eval_report.add_argument("--results", default="data/results/main.json")
    eval_report.add_argument("--offpeak", default="data/results/offpeak.json")
    eval_report.set_defaults(func=cmd_eval_report)

    e2e = subparsers.add_parser("e2e", help="the real test-mode end-to-end run").add_subparsers(
        dest="command", required=True
    )
    e2e_verify = e2e.add_parser(
        "verify", help="check and print the ledger entries the real run produced"
    )
    e2e_verify.set_defaults(func=cmd_e2e_verify)

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
