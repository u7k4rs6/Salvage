"""Demo reset: put the database back to an empty world without touching the schema.

A scenario is a whole world. Running a second one into a database that already holds one is not a
longer demo, it is two worlds interleaved, and the first thing it does is collide on a customer
reference hash. So the Scenario Runner resets before it runs.

Rows are deleted rather than the file being unlinked. The API serves requests from a thread pool
and each thread holds its own open connection (docs/BUILD_LOG.md, M2 carry-over 4); deleting the
file leaves every one of those connections pointing at an inode that no longer exists, and the
next request writes into a database nobody can see. Deleting rows is visible to every connection
immediately because it goes through SQLite's own locking.
"""

from __future__ import annotations

import sqlite3

# Children before parents. Foreign keys are on (salvage/db.py), so this order is enforced rather
# than advisory: the first version of this list put `incidents` above `checkout_hints`, which
# references it, and the reset failed with a constraint error instead of quietly leaving orphans.
# `_check_tables_are_covered` below fails the test suite if a migration adds a table this misses.
TABLES = (
    "recovery_routes",
    "customer_comms",
    "actions",
    "escalations",
    "checkout_hints",
    "recovery_cases",
    "incidents",
    "sim_truth_attempts",
    "sim_truth_incidents",
    "sim_runs",
    "payment_attempts",
    "orders",
    "customers",
    "segments_stats",
    "webhook_events",
    "llm_cache",
    "config_changes",
    "ledger",
)


def reset(conn: sqlite3.Connection, *, keep_ledger: bool = False) -> dict[str, int]:
    """Empty every table. Returns the row count removed per table.

    `keep_ledger` exists for one case only: rehearsing the kill switch, where the point is to show
    that the suspension was recorded and survived. Every other caller wants the ledger gone too,
    because a chain whose entries refer to incidents that no longer exist verifies perfectly and
    describes nothing.
    """
    removed: dict[str, int] = {}
    with conn:
        for table in TABLES:
            if table == "ledger" and keep_ledger:
                continue
            count = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            if count:
                conn.execute(f"DELETE FROM {table}")
                removed[table] = int(count)
    conn.execute("VACUUM")
    orphans = conn.execute("PRAGMA foreign_key_check").fetchall()
    if orphans:
        raise RuntimeError(f"reset left {len(orphans)} orphaned rows: {orphans[:3]}")
    return removed


# The migration bookkeeping table is deliberately left alone: emptying it would make the next
# connection re-run every migration against a schema that already has it.
KEPT = frozenset({"schema_migrations"})


def table_names(conn: sqlite3.Connection) -> set[str]:
    """Every table a reset should empty, so a test can prove TABLES covers all of them."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {str(row["name"]) for row in rows} - KEPT


def is_empty(conn: sqlite3.Connection) -> bool:
    for table in TABLES:
        if conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None:
            return False
    return True
