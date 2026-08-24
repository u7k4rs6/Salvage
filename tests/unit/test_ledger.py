"""Ledger behaviour from docs/03_SECURITY_AND_ACCESS.md section 8."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from salvage.db import open_migrated
from salvage.ledger import (
    GENESIS_HASH,
    Ledger,
    canonical_json,
    export_jsonl,
    load_export,
    verify,
    verify_entries,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def conn(tmp_path):
    c = open_migrated(tmp_path / "led.db")
    yield c
    c.close()


def _append_some(ledger: Ledger, n: int = 5) -> None:
    for i in range(n):
        ledger.append("incident.opened", "incident", f"inc_{i}", {"i": i, "z": [1, 2]}, ts=1000 + i)


def test_first_entry_chains_to_the_genesis_constant(conn):
    entry = Ledger(conn).append("test", "ref", "r1", {"a": 1}, ts=10)
    assert entry.seq == 1
    assert entry.prev_hash == GENESIS_HASH


def test_sequence_is_gapless_and_chained(conn):
    ledger = Ledger(conn)
    _append_some(ledger, 5)
    entries = ledger.entries()
    assert [e.seq for e in entries] == [1, 2, 3, 4, 5]
    for previous, current in zip(entries, entries[1:], strict=False):
        assert current.prev_hash == previous.hash


def test_verify_passes_on_an_untouched_chain(conn):
    _append_some(Ledger(conn), 20)
    result = verify(conn)
    assert result.ok
    assert result.entries == 20
    assert result.broken_seq is None
    assert str(result).startswith("Chain intact, 20 entries, head hash ")


def test_verify_is_true_on_an_empty_ledger(conn):
    result = verify(conn)
    assert result.ok
    assert result.entries == 0
    assert result.head_hash == GENESIS_HASH


def test_verify_reports_the_first_broken_sequence(conn):
    _append_some(Ledger(conn), 6)
    conn.execute("UPDATE ledger SET payload_json = ? WHERE seq = 4", ('{"i":999}',))
    result = verify(conn)
    assert not result.ok
    assert result.broken_seq == 4
    assert "hash" in result.detail


def test_verify_catches_a_deleted_middle_entry(conn):
    _append_some(Ledger(conn), 6)
    conn.execute("DELETE FROM ledger WHERE seq = 3")
    result = verify(conn)
    assert not result.ok
    assert result.broken_seq == 4


def test_verify_catches_a_truncated_tail_reinserted_with_a_forged_hash(conn):
    ledger = Ledger(conn)
    _append_some(ledger, 4)
    # Rewrite entry 3 keeping its own hash consistent but not its link to entry 2.
    conn.execute("UPDATE ledger SET prev_hash = ? WHERE seq = 3", ("0" * 64,))
    result = verify(conn)
    assert not result.ok
    assert result.broken_seq == 3


def test_canonical_json_is_stable_across_key_order():
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})
    assert canonical_json({"a": "₹"}) == '{"a":"\\u20b9"}'
    assert "\n" not in canonical_json({"a": "line\nbreak"})


def test_export_round_trips_and_verifies(conn, tmp_path):
    _append_some(Ledger(conn), 7)
    out = tmp_path / "ledger.jsonl"
    written = export_jsonl(conn, out)
    assert written == 7
    genesis, entries = load_export(out)
    assert genesis == GENESIS_HASH
    assert verify_entries(entries).ok


def test_offline_script_verifies_a_good_export(conn, tmp_path):
    _append_some(Ledger(conn), 5)
    out = tmp_path / "ledger.jsonl"
    export_jsonl(conn, out)
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "verify_ledger.py"), str(out)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Chain intact, 5 entries" in proc.stdout


def test_offline_script_rejects_a_tampered_export(conn, tmp_path):
    _append_some(Ledger(conn), 5)
    out = tmp_path / "ledger.jsonl"
    export_jsonl(conn, out)
    lines = out.read_text().splitlines()
    record = json.loads(lines[3])
    record["payload_json"] = '{"i":42}'
    lines[3] = json.dumps(record, sort_keys=True)
    out.write_text("\n".join(lines) + "\n")
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "verify_ledger.py"), str(out)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "broken at sequence" in proc.stdout


def test_export_contains_no_phone_or_email(conn, tmp_path):
    """Security doc section 5: exports contain no PII by construction."""
    import re

    ledger = Ledger(conn)
    ledger.append(
        "comm.sent",
        "customer",
        "a" * 64,
        {"ref_hash": "a" * 64, "template_id": "recovery_v1", "locale": "en"},
        ts=1,
    )
    out = tmp_path / "ledger.jsonl"
    export_jsonl(conn, out)
    text = out.read_text()
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
    # The boundaries are on alphanumerics, not just digits: a sha256 ref_hash is 64 hex
    # characters and will contain a ten-digit run that looks like a mobile number by accident.
    assert not re.search(r"(?<![0-9A-Za-z])(?:\+91[-\s]?)?[6-9]\d{9}(?![0-9A-Za-z])", text)


def test_ledger_has_no_mutating_verbs():
    """The writer class exposes append and readers, nothing else."""
    public = {name for name in vars(Ledger) if not name.startswith("_")}
    assert public == {"append", "head", "count", "iter_entries", "entries"}
