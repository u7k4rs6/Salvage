"""Ledger routes: browse, verify, export.

docs/04_FRONTEND_SPEC.md section 4.4. The page's job is to prove the audit trail is real, and the
note under its title states what the chain proves and what it does not, which is written here so
the frontend and the document cannot drift apart.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

from salvage.api.deps import ConnFactory
from salvage.ledger import GENESIS_HASH, Ledger, canonical_json, verify

router = APIRouter(prefix="/api/ledger", tags=["ledger"])

# Shown under the title on the Ledger page. docs/03_SECURITY_AND_ACCESS.md section 8: "What the
# ledger proves: that the record has not been altered after the fact. What it does not prove: that
# the process wrote the truth. That distinction is stated on the ledger page so the demo does not
# overclaim."
PROVES = (
    "This chain proves the record has not been altered after it was written: every entry commits "
    "to the one before it, and changing any byte of any entry breaks verification from that point "
    "on. It does not prove the process wrote the truth. A wrong decision, faithfully recorded, "
    "verifies perfectly."
)


@router.get("")
def list_entries(
    connection_factory: ConnFactory,
    kind: str | None = Query(default=None),
    ref_type: str | None = Query(default=None),
    ref_id: str | None = Query(default=None),
    since: int | None = Query(default=None),
    until: int | None = Query(default=None),
    cursor: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    conn = connection_factory()
    clauses, args = ["seq > ?"], [cursor]
    for column, value in (("kind", kind), ("ref_type", ref_type), ("ref_id", ref_id)):
        if value:
            clauses.append(f"{column} = ?")
            args.append(value)
    if since is not None:
        clauses.append("ts >= ?")
        args.append(since)
    if until is not None:
        clauses.append("ts <= ?")
        args.append(until)

    where = " AND ".join(clauses)
    rows = conn.execute(
        f"SELECT * FROM ledger WHERE {where} ORDER BY seq LIMIT ?", (*args, limit + 1)
    ).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]

    total = conn.execute("SELECT COUNT(*) AS n FROM ledger").fetchone()["n"]
    kinds = [
        str(row["kind"]) for row in conn.execute("SELECT DISTINCT kind FROM ledger ORDER BY 1")
    ]
    return {
        "clock": "sim",
        "total": int(total),
        "kinds": kinds,
        "next_cursor": int(rows[-1]["seq"]) if rows and has_more else None,
        "proves": PROVES,
        "entries": [
            {
                "seq": int(row["seq"]),
                "ts": int(row["ts"]),
                "kind": str(row["kind"]),
                "ref_type": str(row["ref_type"]),
                "ref_id": str(row["ref_id"]),
                "hash": str(row["hash"]),
                "prev_hash": str(row["prev_hash"]),
                "payload": json.loads(row["payload_json"]),
            }
            for row in rows
        ],
    }


@router.post("/verify")
def verify_chain(connection_factory: ConnFactory) -> dict[str, Any]:
    """The Verify button. Recomputes the whole chain and reports the first broken sequence."""
    result = verify(connection_factory())
    return {
        "ok": result.ok,
        "entries": result.entries,
        "head_hash": result.head_hash,
        "broken_seq": result.broken_seq,
        "detail": result.detail,
        "message": str(result),
        "genesis_hash": GENESIS_HASH,
        "proves": PROVES,
    }


@router.get("/export", response_class=PlainTextResponse)
def export(
    connection_factory: ConnFactory,
    since: int | None = Query(default=None),
    until: int | None = Query(default=None),
    ref_id: str | None = Query(default=None),
) -> str:
    """JSONL with the hashes included, byte-identical to `salvage ledger export`.

    Served as text so the browser downloads it and so a reviewer can pipe it straight into
    scripts/verify_ledger.py, which is the whole point of the format.

    A slice filtered by ref_id will not verify as a chain on its own, and that is correct: the
    hashes commit to the entries between, so a subset is evidence about entries, not a chain.
    """
    conn = connection_factory()
    header = canonical_json(
        {"type": "salvage.ledger.export", "version": 1, "genesis_hash": GENESIS_HASH}
    )
    lines = [header]
    for entry in Ledger(conn).iter_entries():
        if since is not None and entry.ts < since:
            continue
        if until is not None and entry.ts > until:
            continue
        # A slice for one incident. Sequence numbers stay as they are, so an exported slice is a
        # subset of the chain rather than a renumbered chain of its own, and a reader can see the
        # gaps where other incidents' entries sit.
        if ref_id is not None and entry.ref_id != ref_id:
            continue
        lines.append(json.dumps(entry.to_dict(), sort_keys=True))
    return "\n".join(lines) + "\n"
