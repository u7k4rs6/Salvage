"""The minimal CLI: every command in the M1 brief."""

from __future__ import annotations

import json
import re

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
        "webhooks",
        "serve",
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
