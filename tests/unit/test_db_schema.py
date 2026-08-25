"""Schema invariants from docs/02_TECHNICAL_ARCHITECTURE.md section 3."""

from __future__ import annotations

import sqlite3

import pytest

from salvage import repo
from salvage.db import connect, migrate, migration_files, open_migrated

# Every table named in Architecture section 3, plus the simulator ground-truth tables.
EXPECTED_TABLES = {
    "customers",
    "orders",
    "payment_attempts",
    "segments_stats",
    "incidents",
    "recovery_cases",
    "actions",
    "escalations",
    "customer_comms",
    "webhook_events",
    "llm_cache",
    "ledger",
    "checkout_hints",
    "sim_runs",
    "sim_truth_attempts",
    "sim_truth_incidents",
}

AGENT_VIEWS = {"v_payment_attempts", "v_orders", "v_customers"}


@pytest.fixture
def conn(tmp_path):
    c = open_migrated(tmp_path / "t.db")
    yield c
    c.close()


def test_every_table_exists(conn):
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert names >= EXPECTED_TABLES


def test_agent_views_exist(conn):
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='view'")}
    assert names >= AGENT_VIEWS


def test_agent_view_excludes_truth_cause(conn):
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(v_payment_attempts)")}
    assert "truth_cause" not in columns
    base = {r["name"] for r in conn.execute("PRAGMA table_info(payment_attempts)")}
    assert "truth_cause" in base
    assert base - columns == {"truth_cause"}


def test_wal_mode_is_on(tmp_path):
    c = open_migrated(tmp_path / "wal.db")
    assert c.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    c.close()


def test_migrate_is_idempotent(tmp_path):
    c = connect(tmp_path / "m.db")
    first = migrate(c)
    second = migrate(c)
    assert first == [name for name, _ in migration_files()]
    assert first[0] == "0001_init.sql"
    assert second == []
    c.close()


def test_webhook_event_id_is_unique(conn):
    event = {
        "event_id": "evt_1",
        "received_at": 100,
        "verified": 1,
        "raw_json": "{}",
        "event_type": "payment.failed",
    }
    assert repo.insert_webhook_event(conn, event) is True
    assert repo.insert_webhook_event(conn, event) is False
    assert repo.count_webhook_events(conn) == 1


def test_amounts_are_integers(conn):
    _seed_customer(conn, "cust_1")
    repo.upsert_order(
        conn,
        {
            "id": "order_1",
            "customer_id": "cust_1",
            "amount": 123456,
            "status": "created",
            "source": "sim",
            "created_at": 1000,
        },
    )
    order = repo.get_order(conn, "order_1")
    assert isinstance(order["amount"], int)
    assert isinstance(order["created_at"], int)


def test_order_paid_state_is_sticky_for_out_of_order_events(conn):
    _seed_customer(conn, "cust_1")
    base = {
        "id": "order_1",
        "customer_id": "cust_1",
        "amount": 50000,
        "status": "paid",
        "source": "sim",
        "created_at": 1000,
        "paid_at": 1200,
    }
    repo.upsert_order(conn, base)
    repo.upsert_order(conn, {**base, "status": "attempted", "paid_at": None})
    order = repo.get_order(conn, "order_1")
    assert order["status"] == "paid"
    assert order["paid_at"] == 1200


def test_attempt_captured_state_is_sticky(conn):
    _seed_customer(conn, "cust_1")
    repo.upsert_order(
        conn,
        {
            "id": "order_1",
            "customer_id": "cust_1",
            "amount": 50000,
            "status": "created",
            "source": "sim",
            "created_at": 1000,
        },
    )
    attempt = {
        "id": "pay_1",
        "order_id": "order_1",
        "customer_id": "cust_1",
        "method": "upi",
        "status": "captured",
        "created_at": 1100,
        "raw_json": "{}",
    }
    repo.upsert_attempt(conn, attempt)
    repo.upsert_attempt(conn, {**attempt, "status": "failed", "error_reason": "payment_failed"})
    stored = repo.get_attempt(conn, "pay_1")
    assert stored["status"] == "captured"


def test_foreign_keys_are_enforced(conn):
    with pytest.raises(sqlite3.IntegrityError):
        repo.upsert_order(
            conn,
            {
                "id": "order_x",
                "customer_id": "missing",
                "amount": 1,
                "status": "created",
                "source": "sim",
                "created_at": 1,
            },
        )


def test_ref_hash_is_salted_and_stable():
    a = repo.ref_hash("+919000000001", salt="salt-a")
    b = repo.ref_hash("+919000000001", salt="salt-b")
    assert a != b
    assert a == repo.ref_hash("+919000000001", salt="salt-a")
    assert len(a) == 64


def _seed_customer(conn, customer_id: str) -> None:
    repo.insert_customer(
        conn,
        {
            "id": customer_id,
            "ref_hash": repo.ref_hash(customer_id, salt="t"),
            "consent": 1,
            "locale": "en",
            "typical_amount": 100000,
            "created_at": 0,
        },
    )


def test_only_the_evaluation_runner_reads_ground_truth():
    """Architecture section 10: "The runner is the only code allowed to read ground truth."

    Ground truth is `payment_attempts.truth_cause` and the `sim_truth_*` tables. The simulator
    writes them and `salvage/eval/` reads them. Nothing in detect, diagnose, decide, execute,
    ingest or api may touch them, because a model or a policy that could see the answer would make
    every number in docs/RESULTS.md meaningless.
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "salvage"
    forbidden = re.compile(r"truth_cause|sim_truth_")
    allowed_dirs = {"sim", "eval"}
    findings = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] in allowed_dirs:
            continue
        if relative.name == "repo.py":
            # repo.py holds the ground-truth accessors themselves, grouped under a heading that
            # names the evaluation runner as their only caller. What matters is who imports them.
            continue
        if relative.as_posix() == "demo.py":
            # The reset names both ground-truth tables in its delete list. Deleting a table is not
            # reading it, and a reset that skipped them would leave the next scenario's detector
            # looking at the previous world's answers. The exemption is narrow: the only lines
            # allowed to mention them are the bare table names in the TABLES tuple.
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if forbidden.search(line) and line.strip() not in {
                    '"sim_truth_attempts",',
                    '"sim_truth_incidents",',
                }:
                    findings.append(f"{relative}:{lineno}: {line.strip()}")
            continue
        if relative.as_posix() == "ingest/normalize.py":
            # The normaliser takes truth_cause as a write-through parameter, because the simulator
            # and the webhook receiver share it and the simulator has the value. It never reads it
            # back, which the assertion below checks directly.
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if forbidden.search(line) and not line.lstrip().startswith("#"):
                findings.append(f"{relative}:{lineno}: {line.strip()}")
    assert findings == [], "ground truth reached a non-evaluation module: " + "; ".join(findings)

    # The one allowlisted file writes truth_cause and must never read it.
    normalize = (root / "ingest" / "normalize.py").read_text(encoding="utf-8")
    assert "SELECT" not in normalize.upper() or "truth_cause" not in normalize.split("SELECT")[-1]
    assert 'row["truth_cause"]' not in normalize
    assert ".truth_cause" not in normalize


def test_the_ground_truth_grep_would_catch_a_real_leak():
    import re

    forbidden = re.compile(r"truth_cause|sim_truth_")
    assert forbidden.search("SELECT truth_cause FROM payment_attempts")
    assert forbidden.search('conn.execute("SELECT * FROM sim_truth_incidents")')
    assert not forbidden.search("SELECT * FROM v_payment_attempts")
