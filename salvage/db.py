"""SQLite connection and migration runner.

One file database at data/salvage.db (docs/02_TECHNICAL_ARCHITECTURE.md section 3). WAL mode, no
ORM. Migrations are numbered SQL files in migrations/ applied in order at startup and recorded in
schema_migrations so a second run is a no-op.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from salvage.config import get_settings

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
_MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open a connection with the pragmas the architecture fixes.

    WAL is set once and persists in the database file; setting it on every connection is harmless
    and means a fresh file gets it too. foreign_keys is per connection, so it must be set here.
    """
    if path is None:
        path = get_settings().salvage_db_path
    path = Path(path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    # No check_same_thread=False. A connection belongs to the thread that opened it. Sharing one
    # across threads meant two requests could interleave BEGIN IMMEDIATE and COMMIT on the same
    # connection, which silently commits half of one transaction inside the other. Code that needs
    # a connection from a worker thread calls thread_connection() below.
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Explicit transaction. isolation_level is None so sqlite3 does not manage them for us."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def migration_files() -> list[tuple[str, Path]]:
    files = []
    for path in sorted(MIGRATIONS_DIR.iterdir()):
        match = _MIGRATION_NAME.match(path.name)
        if match:
            files.append((path.name, path))
    return files


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply every pending migration. Returns the names applied this call."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " name TEXT PRIMARY KEY, applied_at INTEGER NOT NULL DEFAULT (strftime('%s','now')))"
    )
    already = {row["name"] for row in conn.execute("SELECT name FROM schema_migrations")}
    applied: list[str] = []
    for name, path in migration_files():
        if name in already:
            continue
        sql = path.read_text(encoding="utf-8")
        # executescript issues its own COMMIT, so it cannot sit inside transaction().
        conn.executescript(sql)
        conn.execute("INSERT INTO schema_migrations (name) VALUES (?)", (name,))
        applied.append(name)
    return applied


def open_migrated(path: Path | str | None = None) -> sqlite3.Connection:
    """Connect and bring the schema up to date. What every entry point calls."""
    conn = connect(path)
    migrate(conn)
    return conn


# ---------------------------------------------------------------------------
# Per-thread connections
# ---------------------------------------------------------------------------

_local = threading.local()


class InMemoryNotShareable(ValueError):
    """A per-thread in-memory database would be a different database per thread."""


def thread_connection(path: Path | str | None = None) -> sqlite3.Connection:
    """The calling thread's connection to this database, opened on first use.

    The API runs synchronous request work in a worker thread pool, and a thread pool hands the
    same task to whichever thread is free. A connection per thread is the smallest thing that is
    actually correct: each thread's transactions are its own, SQLite serialises the writes through
    the file lock, and busy_timeout absorbs the contention. Salvage is single-process and its
    write rate is a webhook at a time, so the file lock is not a bottleneck.

    Connections are never closed here. There is one thread pool for the life of the process and a
    handful of threads in it, so the connections are a fixed small cost rather than a leak.
    """
    if path is None:
        path = get_settings().salvage_db_path
    if str(path) == ":memory:":
        raise InMemoryNotShareable(
            "an in-memory database cannot be shared across threads; use a file path"
        )
    key = str(Path(path).resolve())
    registry = getattr(_local, "connections", None)
    if registry is None:
        registry = {}
        _local.connections = registry
    conn = registry.get(key)
    if conn is None:
        conn = open_migrated(path)
        registry[key] = conn
    return conn


def close_thread_connections() -> None:
    """Close and forget this thread's connections. Used by tests between databases."""
    registry = getattr(_local, "connections", None)
    if not registry:
        return
    for conn in registry.values():
        conn.close()
    registry.clear()
