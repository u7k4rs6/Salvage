"""Escalation queue: the human-in-the-loop surface.

docs/04_FRONTEND_SPEC.md section 4.3. The decision is a mutating route and needs the token, and it
is itself ledgered (docs/03_SECURITY_AND_ACCESS.md section 6: "Approval is a dashboard action
behind the token and is itself ledgered").
"""

from __future__ import annotations

import json
import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from salvage.api.deps import ConnFactory, require_token
from salvage.api.stream import BUS
from salvage.ledger import Ledger

router = APIRouter(prefix="/api/escalations", tags=["escalations"])


class Decision(BaseModel):
    model_config = {"extra": "forbid"}

    decision: Literal["approve", "reject"]
    # The spec requires a one-line note on the confirmation, so the schema requires it too. An
    # approval with no reason is not a record of anything.
    note: str = Field(min_length=1, max_length=500)


def _row(conn, row: Any) -> dict[str, Any]:
    incident = conn.execute(
        "SELECT segment_key, root_cause, confidence, at_risk_amount FROM incidents WHERE id = ?",
        (row["incident_id"],),
    ).fetchone()
    return {
        "id": str(row["id"]),
        "incident_id": str(row["incident_id"]),
        "reason": str(row["reason"]),
        "evidence": json.loads(row["evidence_json"] or "{}"),
        "proposed_action": json.loads(row["proposed_action_json"] or "{}"),
        "decision": row["decision"],
        "decided_at": row["decided_at"],
        "note": row["note"],
        "created_at": int(row["created_at"]),
        "incident": dict(incident) if incident else None,
    }


@router.get("")
def list_escalations(
    connection_factory: ConnFactory,
    status: str = Query(default="pending", pattern="^(pending|decided|all)$"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    conn = connection_factory()
    where = {
        "pending": "WHERE decision IS NULL",
        "decided": "WHERE decision IS NOT NULL",
        "all": "",
    }[status]
    rows = conn.execute(
        f"SELECT * FROM escalations {where} ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return {"clock": "sim", "status": status, "escalations": [_row(conn, row) for row in rows]}


@router.post("/{escalation_id}/decision", dependencies=[Depends(require_token)])
def decide(
    escalation_id: str, decision: Decision, connection_factory: ConnFactory
) -> dict[str, Any]:
    conn = connection_factory()
    row = conn.execute("SELECT * FROM escalations WHERE id = ?", (escalation_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"no escalation {escalation_id}")
    if row["decision"] is not None:
        raise HTTPException(
            status_code=409,
            detail=f"already {row['decision']} at {row['decided_at']}",
        )

    now = int(time.time())
    conn.execute(
        "UPDATE escalations SET decision = ?, decided_at = ?, note = ? WHERE id = ?",
        (decision.decision, now, decision.note, escalation_id),
    )
    Ledger(conn).append(
        "escalation.decided",
        "escalation",
        escalation_id,
        {
            "incident_id": str(row["incident_id"]),
            "decision": decision.decision,
            "note": decision.note[:500],
        },
        ts=now,
    )
    BUS.publish(
        "escalation.decided",
        {
            "id": escalation_id,
            "decision": decision.decision,
            "incident_id": str(row["incident_id"]),
        },
    )
    return {"id": escalation_id, "decision": decision.decision, "decided_at": now}
