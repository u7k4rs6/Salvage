"""docs/03_SECURITY_AND_ACCESS.md section 8:

  "There is no update or delete function anywhere in the codebase, and a test greps for
  'UPDATE ledger' and 'DELETE FROM ledger' to keep it that way."

This is that test. It greps the shipped source, not the tests: the ledger unit tests deliberately
tamper with the table to prove verification catches it, and that is the one place allowed to.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Directories that ship. tests/ is excluded on purpose, see the module docstring.
SHIPPED_DIRS = ("salvage", "scripts", "migrations")

FORBIDDEN = (
    re.compile(r"\bUPDATE\s+ledger\b", re.IGNORECASE),
    re.compile(r"\bDELETE\s+FROM\s+ledger\b", re.IGNORECASE),
    re.compile(r"\bDROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?ledger\b", re.IGNORECASE),
    re.compile(r"\bTRUNCATE\s+ledger\b", re.IGNORECASE),
    re.compile(r"\bINSERT\s+OR\s+REPLACE\s+INTO\s+ledger\b", re.IGNORECASE),
)


def shipped_files() -> list[Path]:
    files: list[Path] = []
    for directory in SHIPPED_DIRS:
        for path in sorted((REPO_ROOT / directory).rglob("*")):
            if path.is_file() and path.suffix in {".py", ".sql"}:
                files.append(path)
    return files


def test_shipped_source_has_no_ledger_mutation():
    findings: list[str] = []
    for path in shipped_files():
        # This file's own patterns are the strings being searched for.
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pattern in FORBIDDEN:
                if pattern.search(line):
                    findings.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    assert findings == [], "ledger must be append only, found: " + "; ".join(findings)


def test_the_grep_would_actually_catch_something(tmp_path):
    """A test that greps is worthless if the pattern does not match. Prove it does."""
    for sql in (
        "UPDATE ledger SET hash = 'x'",
        "delete from ledger where seq = 1",
        "DROP TABLE IF EXISTS ledger",
        "INSERT OR REPLACE INTO ledger (seq) VALUES (1)",
    ):
        assert any(pattern.search(sql) for pattern in FORBIDDEN), sql


def test_the_grep_does_not_fire_on_legitimate_lines():
    for sql in (
        "INSERT INTO ledger (seq, ts) VALUES (?, ?)",
        "SELECT * FROM ledger ORDER BY seq",
        "UPDATE incidents SET closed_at = ? WHERE id = ?",
        "DELETE FROM webhook_events WHERE event_id = ?",
    ):
        assert not any(pattern.search(sql) for pattern in FORBIDDEN), sql


def test_shipped_files_were_actually_scanned():
    files = shipped_files()
    names = {p.name for p in files}
    assert "ledger.py" in names
    assert "0001_init.sql" in names
    assert len(files) > 5
