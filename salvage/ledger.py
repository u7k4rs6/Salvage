"""Append-only hash-chained ledger.

docs/03_SECURITY_AND_ACCESS.md section 8 fixes the design:

  Append only. The writer exposes append() and nothing else. There is no update or delete
  function anywhere in the codebase, and tests/unit/test_ledger_append_only.py greps the shipped
  source for the SQL verbs that would mutate this table, to keep it that way. (That test holds
  the patterns; this docstring does not spell them out, or it would match itself.)

  Hash chain. hash = sha256(seq || ts || kind || ref_type || ref_id || canonical_json(payload)
  || prev_hash). The first entry's prev_hash is a fixed genesis constant.

  Verification recomputes the chain and reports the first broken sequence number.

  Export writes JSONL with the hashes included so a reviewer can verify offline with
  scripts/verify_ledger.py.

What the chain proves: the record has not been altered after the fact. What it does not prove:
that the process wrote the truth. That distinction is stated on the ledger page in the dashboard
so the demo does not overclaim.

The ledger carries no contact, email, name or order notes (security doc section 5). It references
customers by ref_hash and orders by id. append() does not enforce that, because it cannot know
what a payload means; the callers do, and an export test asserts no export line matches a phone or
email pattern.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# sha256(b"salvage.ledger.genesis.v1"). A fixed constant, never derived from data, so an empty
# ledger and a truncated-to-empty ledger are distinguishable only by the entries themselves.
GENESIS_HASH = "e033221f96520f784ef136e1ba52ae6b04cba31331157e223f1c97e64ae59524"

# Field separator for the pre-image. canonical_json() never emits a raw newline (json.dumps
# escapes every control character), so a newline separator cannot be forged from inside a field.
_SEP = b"\n"


def canonical_json(payload: Any) -> str:
    """Canonical JSON: sorted keys, no insignificant whitespace, ASCII-escaped.

    The exact string returned here is what gets hashed and what gets stored in payload_json, so a
    verifier never has to re-serialise and never has to agree with us about float formatting or
    key order.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def entry_hash(
    seq: int, ts: int, kind: str, ref_type: str, ref_id: str, payload_json: str, prev_hash: str
) -> str:
    """sha256 over the pre-image described in the security doc."""
    digest = hashlib.sha256()
    for field in (
        str(seq).encode(),
        str(ts).encode(),
        kind.encode(),
        ref_type.encode(),
        ref_id.encode(),
        payload_json.encode(),
        prev_hash.encode(),
    ):
        digest.update(field)
        digest.update(_SEP)
    return digest.hexdigest()


@dataclass(frozen=True)
class LedgerEntry:
    seq: int
    ts: int
    kind: str
    ref_type: str
    ref_id: str
    payload_json: str
    prev_hash: str
    hash: str

    @property
    def payload(self) -> Any:
        return json.loads(self.payload_json)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "ts": self.ts,
            "kind": self.kind,
            "ref_type": self.ref_type,
            "ref_id": self.ref_id,
            "payload_json": self.payload_json,
            "prev_hash": self.prev_hash,
            "hash": self.hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LedgerEntry:
        return cls(
            seq=int(data["seq"]),
            ts=int(data["ts"]),
            kind=str(data["kind"]),
            ref_type=str(data["ref_type"]),
            ref_id=str(data["ref_id"]),
            payload_json=str(data["payload_json"]),
            prev_hash=str(data["prev_hash"]),
            hash=str(data["hash"]),
        )

    def recomputed_hash(self) -> str:
        return entry_hash(
            self.seq,
            self.ts,
            self.kind,
            self.ref_type,
            self.ref_id,
            self.payload_json,
            self.prev_hash,
        )


class Ledger:
    """The only writer. It appends and it reads. It has no other verbs, by design."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # -- write ------------------------------------------------------------

    def append(self, kind: str, ref_type: str, ref_id: str, payload: Any, ts: int) -> LedgerEntry:
        """Append one entry and return it.

        Runs in an IMMEDIATE transaction so the read of the head and the write of the successor
        cannot interleave with another writer. Salvage is single-process, but the demo can have
        the API and a simulator run touching the same file.
        """
        conn = self._conn
        payload_json = canonical_json(payload)
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute("SELECT seq, hash FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()
            if row is None:
                seq, prev_hash = 1, GENESIS_HASH
            else:
                seq, prev_hash = int(row["seq"]) + 1, str(row["hash"])
            digest = entry_hash(seq, ts, kind, ref_type, ref_id, payload_json, prev_hash)
            conn.execute(
                "INSERT INTO ledger (seq, ts, kind, ref_type, ref_id, payload_json, prev_hash,"
                " hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (seq, ts, kind, ref_type, ref_id, payload_json, prev_hash, digest),
            )
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
        return LedgerEntry(seq, ts, kind, ref_type, ref_id, payload_json, prev_hash, digest)

    # -- read -------------------------------------------------------------

    def head(self) -> LedgerEntry | None:
        row = self._conn.execute("SELECT * FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()
        return LedgerEntry.from_dict(dict(row)) if row else None

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) AS n FROM ledger").fetchone()["n"])

    def iter_entries(
        self, *, since_seq: int = 0, kind: str | None = None, ref_id: str | None = None
    ) -> Iterator[LedgerEntry]:
        sql = "SELECT * FROM ledger WHERE seq > ?"
        params: list[Any] = [since_seq]
        if kind is not None:
            sql += " AND kind = ?"
            params.append(kind)
        if ref_id is not None:
            sql += " AND ref_id = ?"
            params.append(ref_id)
        sql += " ORDER BY seq"
        for row in self._conn.execute(sql, tuple(params)):
            yield LedgerEntry.from_dict(dict(row))

    def entries(self, **kwargs: Any) -> list[LedgerEntry]:
        return list(self.iter_entries(**kwargs))


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    entries: int
    head_hash: str | None
    broken_seq: int | None
    detail: str

    def __str__(self) -> str:
        if self.ok:
            short = (self.head_hash or "")[:12]
            return f"Chain intact, {self.entries} entries, head hash {short}"
        return f"Broken at sequence {self.broken_seq}: {self.detail}"


def verify_entries(entries: list[LedgerEntry]) -> VerifyResult:
    """Recompute the chain over an ordered list of entries.

    Reports the first broken sequence number, which is what the security doc asks for. Four things
    can break: a sequence number that is not its predecessor plus one, a prev_hash that does not
    match the predecessor's hash, a stored hash that does not match the recomputed one, and a
    first entry whose prev_hash is not the genesis constant.
    """
    prev_hash = GENESIS_HASH
    expected_seq = 1
    for entry in entries:
        if entry.seq != expected_seq:
            return VerifyResult(
                False,
                len(entries),
                None,
                entry.seq,
                f"expected sequence {expected_seq}, found {entry.seq}",
            )
        if entry.prev_hash != prev_hash:
            return VerifyResult(
                False,
                len(entries),
                None,
                entry.seq,
                "prev_hash does not match the previous entry's hash",
            )
        recomputed = entry.recomputed_hash()
        if recomputed != entry.hash:
            return VerifyResult(
                False,
                len(entries),
                None,
                entry.seq,
                "stored hash does not match the recomputed hash",
            )
        prev_hash = entry.hash
        expected_seq += 1
    # On an empty ledger the head is the genesis constant, which is what the offline
    # verifier reports too. Keeping the two in step means one output shape to read.
    return VerifyResult(True, len(entries), prev_hash, None, "ok")


def verify(conn: sqlite3.Connection) -> VerifyResult:
    """Verify the chain in a database."""
    return verify_entries(Ledger(conn).entries())


def export_jsonl(conn: sqlite3.Connection, out_path: Path | str) -> int:
    """Write every entry as one JSON object per line, hashes included.

    The file is self-describing: scripts/verify_ledger.py needs nothing but this file and the
    genesis constant, which is written as the first line's metadata record.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out_path.open("w", encoding="utf-8") as handle:
        header = {"type": "salvage.ledger.export", "version": 1, "genesis_hash": GENESIS_HASH}
        handle.write(json.dumps(header, sort_keys=True) + "\n")
        for entry in Ledger(conn).iter_entries():
            handle.write(json.dumps(entry.to_dict(), sort_keys=True) + "\n")
            written += 1
    return written


def load_export(path: Path | str) -> tuple[str, list[LedgerEntry]]:
    """Read an export back. Returns the genesis hash declared by the file and its entries."""
    genesis = GENESIS_HASH
    entries: list[LedgerEntry] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("type") == "salvage.ledger.export":
                genesis = str(record.get("genesis_hash", GENESIS_HASH))
                continue
            entries.append(LedgerEntry.from_dict(record))
    return genesis, entries
