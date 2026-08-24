"""Verify that a database still holds the event stream the ledger committed to.

The ledger's `sim.run.finished` entry carries a sha256 over the ordered attempt stream. The hash
chain proves that entry has not been edited; this command proves the events it describes have not
been edited either. Together they close the gap the security doc names on the ledger page: the
chain proves the record was not altered after the fact, and this proves the record still matches
what is in the database.

Used by `salvage sim verify-stream <run_id>`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from salvage import repo
from salvage.ledger import Ledger
from salvage.sim.runner import stream_digest


@dataclass(frozen=True)
class StreamVerifyResult:
    ok: bool
    run_id: str
    committed_digest: str | None
    computed_digest: str | None
    committed_attempts: int | None
    computed_attempts: int | None
    detail: str

    def __str__(self) -> str:
        if self.ok:
            short = (self.committed_digest or "")[:12]
            return (
                f"Stream intact for {self.run_id}: {self.computed_attempts} attempts, "
                f"digest {short}"
            )
        return f"Stream mismatch for {self.run_id}: {self.detail}"


class StreamNotCommitted(LookupError):
    """No sim.run.finished ledger entry for this run."""


def latest_run_id(conn) -> str | None:
    run = repo.latest_sim_run(conn)
    return str(run["run_id"]) if run else None


def committed_entry(conn, run_id: str) -> dict:
    """The sim.run.finished payload for a run.

    The last such entry wins if a run id somehow appears twice: the ledger is append only, so a
    second entry is a later statement about the same run, not a replacement of the first.
    """
    entries = [
        entry
        for entry in Ledger(conn).iter_entries(kind="sim.run.finished", ref_id=run_id)
    ]
    if not entries:
        raise StreamNotCommitted(f"no sim.run.finished ledger entry for run {run_id!r}")
    return json.loads(entries[-1].payload_json)


def verify_stream(conn, run_id: str | None = None) -> StreamVerifyResult:
    """Recompute the digest from the database and compare it with the ledger's commitment."""
    if run_id is None:
        run_id = latest_run_id(conn)
        if run_id is None:
            raise StreamNotCommitted("there are no simulator runs in this database")

    run = repo.get_sim_run(conn, run_id)
    if run is None:
        raise StreamNotCommitted(f"no simulator run {run_id!r} in this database")

    payload = committed_entry(conn, run_id)
    committed_digest = payload.get("stream_digest")
    committed_attempts = payload.get("stream_attempts")
    if not committed_digest:
        raise StreamNotCommitted(
            f"the sim.run.finished entry for {run_id!r} carries no stream_digest"
        )

    sim_start = int(payload.get("sim_start", run["sim_start"]))
    sim_end = int(payload.get("sim_end", run["sim_end"]))
    computed_digest, computed_attempts = stream_digest(
        conn, sim_start=sim_start, sim_end=sim_end
    )

    if computed_digest == committed_digest:
        detail = "ok"
        ok = True
    elif computed_attempts != committed_attempts:
        ok = False
        detail = (
            f"attempt count changed: ledger committed to {committed_attempts}, "
            f"database holds {computed_attempts}"
        )
    else:
        ok = False
        detail = (
            f"same number of attempts ({computed_attempts}) but at least one row differs; "
            f"committed {committed_digest[:12]}, computed {computed_digest[:12]}"
        )

    return StreamVerifyResult(
        ok=ok,
        run_id=run_id,
        committed_digest=committed_digest,
        computed_digest=computed_digest,
        committed_attempts=committed_attempts,
        computed_attempts=computed_attempts,
        detail=detail,
    )
