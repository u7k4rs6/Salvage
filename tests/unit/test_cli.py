"""The minimal CLI: every command in the M1 brief."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from salvage.cli import _parse_seeds, build_parser, main


def _run(capsys, argv: list[str]) -> tuple[int, str, str]:
    code = main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_every_documented_command_is_registered():
    parser = build_parser()
    groups = parser._subparsers._group_actions[0].choices  # noqa: SLF001
    assert set(groups) == {
        "db",
        "ledger",
        "sim",
        "detect",
        "diagnose",
        "agent",
        "eval",
        "e2e",
        "webhooks",
        "serve",
        "demo",
    }
    assert set(groups["db"]._subparsers._group_actions[0].choices) == {"migrate"}  # noqa: SLF001
    assert set(groups["ledger"]._subparsers._group_actions[0].choices) == {  # noqa: SLF001
        "verify",
        "export",
    }
    assert set(groups["sim"]._subparsers._group_actions[0].choices) == {  # noqa: SLF001
        "run",
        "verify-stream",
        "organic",
    }
    assert set(groups["detect"]._subparsers._group_actions[0].choices) == {  # noqa: SLF001
        "calibrate"
    }
    assert set(groups["webhooks"]._subparsers._group_actions[0].choices) == {  # noqa: SLF001
        "record",
        "replay",
    }
    assert set(groups["diagnose"]._subparsers._group_actions[0].choices) == {  # noqa: SLF001
        "accuracy",
        "export-prompts",
        "import-fixtures",
        "record-fixtures",
    }
    assert set(groups["agent"]._subparsers._group_actions[0].choices) == {"run"}  # noqa: SLF001
    assert set(groups["eval"]._subparsers._group_actions[0].choices) == {  # noqa: SLF001
        "run",
        "volume",
        "sensitivity",
        "steer-sensitivity",
        "escalation-fix",
        "report",
    }
    assert set(groups["e2e"]._subparsers._group_actions[0].choices) == {"verify"}  # noqa: SLF001
    assert set(groups["demo"]._subparsers._group_actions[0].choices) == {  # noqa: SLF001
        "reset",
        "kill-switch",
    }


def test_no_subcommand_shadows_the_global_db_flag():
    """A subparser option named --db parses fine and then overwrites the global one with its
    own default of None, so the command runs against the default database. That is how
    "salvage --db scratch.db demo reset" emptied the wrong file during the kill-switch
    rehearsal. Nothing below the top level may define --db."""
    parser = build_parser()
    offenders: list[str] = []

    def walk(p, path: str) -> None:
        for action in p._actions:  # noqa: SLF001
            if getattr(action, "choices", None) and hasattr(action, "_name_parser_map"):
                for name, sub in action._name_parser_map.items():  # noqa: SLF001
                    walk(sub, f"{path} {name}".strip())
            elif path and "--db" in (action.option_strings or []):
                offenders.append(f"{path} defines --db")

    walk(parser, "")
    assert offenders == []


def test_the_escalation_fix_sweep_can_name_its_artifact():
    """A follow-up probe over different values is a different result. It wrote to the same file
    as the sweep the report reads, and overwrote it, which is a quiet way to publish a curve
    nobody ran."""
    parser = build_parser()
    groups = parser._subparsers._group_actions[0].choices  # noqa: SLF001
    fix = groups["eval"]._subparsers._group_actions[0].choices["escalation-fix"]  # noqa: SLF001
    out = next(a for a in fix._actions if "--out" in (a.option_strings or []))  # noqa: SLF001
    assert out.default == "escalation_fix.json"

    # The flag existing is not the point. It has to be the thing the command writes to: the first
    # version added the flag and left the filename hardcoded, so the probe overwrote the reported
    # curve again while a passing test said the flag was there.
    source = Path("salvage/cli.py").read_text(encoding="utf-8")
    assert '_write_artifact("escalation_fix.json"' not in source
    assert "_write_artifact(args.out, payload)" in source


def test_seed_spec_parsing():
    assert _parse_seeds("0..4") == [0, 1, 2, 3, 4]
    assert _parse_seeds("0,2,7") == [0, 2, 7]
    assert _parse_seeds(" 3..3 ") == [3]


def test_db_migrate_is_idempotent(capsys, tmp_path):
    db = str(tmp_path / "cli.db")
    code, out, _ = _run(capsys, ["--db", db, "db", "migrate"])
    assert code == 0
    assert "Applied" in out and "migration" in out
    code, out, _ = _run(capsys, ["--db", db, "db", "migrate"])
    assert code == 0
    assert "already up to date" in out


def test_ledger_verify_and_export_on_an_empty_database(capsys, tmp_path):
    db = str(tmp_path / "cli.db")
    out_path = tmp_path / "ledger.jsonl"
    code, out, _ = _run(capsys, ["--db", db, "ledger", "verify"])
    assert code == 0
    assert "Chain intact, 0 entries" in out
    code, out, _ = _run(capsys, ["--db", db, "ledger", "export", "--out", str(out_path)])
    assert code == 0
    assert "Exported 0 entries" in out
    header = json.loads(out_path.read_text().splitlines()[0])
    assert header["type"] == "salvage.ledger.export"


def test_ledger_verify_exits_non_zero_on_a_broken_chain(capsys, tmp_path):
    from salvage.db import open_migrated
    from salvage.ledger import Ledger

    db = tmp_path / "broken.db"
    conn = open_migrated(db)
    Ledger(conn).append("test", "ref", "r", {"a": 1}, ts=1)
    Ledger(conn).append("test", "ref", "r", {"a": 2}, ts=2)
    conn.execute("UPDATE ledger SET payload_json = '{}' WHERE seq = 2")
    conn.close()

    code, out, _ = _run(capsys, ["--db", str(db), "ledger", "verify"])
    assert code == 1
    assert "Broken at sequence 2" in out


def test_webhooks_replay_is_refused_outside_dev(capsys, tmp_path, monkeypatch):
    from salvage.config import reset_settings_cache

    monkeypatch.setenv("SALVAGE_ENV", "demo")
    reset_settings_cache()
    try:
        directory = tmp_path / "webhooks"
        directory.mkdir()
        code, _, err = _run(
            capsys, ["--db", str(tmp_path / "cli.db"), "webhooks", "replay", str(directory)]
        )
        assert code == 2
        assert "SALVAGE_ENV=dev" in err
    finally:
        reset_settings_cache()


def test_webhooks_record_then_replay(capsys, tmp_path, monkeypatch):
    from salvage.config import reset_settings_cache

    monkeypatch.setenv("SALVAGE_ENV", "dev")
    reset_settings_cache()
    try:
        db = tmp_path / "cli.db"
        out_dir = tmp_path / "webhooks"
        code, out, _ = _run(capsys, ["--db", str(db), "webhooks", "record", "--out", str(out_dir)])
        assert code == 0
        assert "Wrote 0 verified event(s)" in out
        code, out, _ = _run(capsys, ["--db", str(db), "webhooks", "replay", str(out_dir)])
        assert code == 0
        assert "Replayed 0 event(s)" in out
    finally:
        reset_settings_cache()


def test_sim_run_produces_events_ground_truth_and_a_verifiable_ledger(
    capsys, tmp_path, small_params_path
):
    """The exit-criterion command, at reduced volume so the test stays quick.

    The CLI always reads the shipped params.yaml, so the run itself goes through the runner with
    the small ones and the CLI is used for the parts that do not depend on scale. The full-scale
    version of this run is in tests/calibration and in the M1 report.
    """
    db = str(tmp_path / "sim.db")

    from salvage.db import open_migrated
    from salvage.detect.run import detect
    from salvage.sim.runner import run_scenario

    conn = open_migrated(db)
    result = run_scenario(conn, scenario="S1", seed=1, params_path=small_params_path)
    assert result.attempts > 0
    assert result.failures > 0
    assert result.truth_rows == result.failures
    detect(conn, eval_start=result.eval_day_start, eval_end=result.eval_day_start + 86400)
    conn.close()

    code, out, _ = _run(capsys, ["--db", db, "ledger", "verify"])
    assert code == 0
    assert re.search(r"Chain intact, \d+ entries", out)


def test_unknown_command_exits_with_usage(capsys):
    with pytest.raises(SystemExit):
        main(["nope"])


def test_e2e_verify_says_so_when_there_is_nothing_to_verify(capsys, tmp_path):
    """The command must not print an empty success when the real run has not happened."""
    code, out, err = _run(capsys, ["--db", str(tmp_path / "e2e.db"), "e2e", "verify"])
    assert code == 1
    assert "No end-to-end ledger entries found" in err


def test_e2e_verify_prints_the_ledger_entries_the_real_run_produced(capsys, tmp_path):
    from salvage.db import open_migrated
    from salvage.ledger import Ledger

    db = tmp_path / "e2e.db"
    conn = open_migrated(db)
    ledger = Ledger(conn)
    ledger.append("e2e.order.created", "order", "order_abc", {"amount": 100}, ts=1)
    ledger.append(
        "e2e.link.created",
        "case",
        "case_abc",
        {"link_id": "plink_abc", "order_id": "order_abc"},
        ts=2,
    )
    ledger.append(
        "e2e.link.paid",
        "case",
        "case_abc",
        {"link_id": "plink_abc", "payment_id": "pay_abc"},
        ts=3,
    )
    ledger.append(
        "webhook.received",
        "webhook_event",
        "evt_abc",
        {"event_type": "payment_link.paid", "verified": True, "acted": True},
        ts=4,
    )
    conn.close()

    code, out, _ = _run(capsys, ["--db", str(db), "e2e", "verify"])
    assert code == 0
    assert "e2e.order.created" in out
    assert "plink_abc" in out
    assert "evt_abc" in out
    assert "Chain intact" in out
    # Hashes and linkage, which is what the report needs.
    assert "prev_hash" in out
    assert "prev_hash matches the hash of the entry before it" in out
    assert "| ledger sequence numbers | 1, 2, 3, 4 |" in out
    assert "| head hash |" in out


def test_e2e_verify_reports_an_incomplete_run(capsys, tmp_path):
    from salvage.db import open_migrated
    from salvage.ledger import Ledger

    db = tmp_path / "e2e2.db"
    conn = open_migrated(db)
    Ledger(conn).append("e2e.order.created", "order", "order_abc", {"amount": 100}, ts=1)
    conn.close()
    code, _, err = _run(capsys, ["--db", str(db), "e2e", "verify"])
    assert code == 1
    assert "Incomplete" in err
