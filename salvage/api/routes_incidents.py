"""Overview and incident routes.

docs/04_FRONTEND_SPEC.md sections 4.1 and 4.2 fix the response shapes. Every amount is paise and
every time is Unix seconds with a `clock` field, formatted client-side (spec section 5).
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from salvage import repo
from salvage.api.deps import ConnFactory, require_token
from salvage.api.stream import BUS
from salvage.detect.segments import ALL_KEY, parse_key
from salvage.detect.thresholds import FROZEN

router = APIRouter(prefix="/api", tags=["incidents"])

# The Overview heatmap's rows. The merchant-wide row is pinned first, as decided in M2: a fault
# that spans every method is attributed to the `all` key by the detector, and without a row for it
# there would be nowhere on the page for a gateway outage to appear.
HEATMAP_METHODS = ("upi", "card", "netbanking", "wallet")


def _latest_window(conn) -> int:
    row = conn.execute("SELECT MAX(window_start) AS w FROM segments_stats").fetchone()
    if row and row["w"] is not None:
        return int(row["w"])
    row = conn.execute("SELECT MAX(created_at) AS c FROM v_payment_attempts").fetchone()
    return int(row["c"]) if row and row["c"] is not None else 0


def _open_incident_by_key(conn) -> dict[str, str]:
    """Segment key to incident id, including every key inside an open incident's scope."""
    mapping: dict[str, str] = {}
    for incident in repo.open_incidents(conn):
        incident_id = str(incident["id"])
        mapping[str(incident["segment_key"])] = incident_id
        for key in json.loads(incident["affected_scope_json"] or "[]"):
            mapping.setdefault(str(key), incident_id)
    return mapping


@router.get("/overview")
def overview(connection_factory: ConnFactory) -> dict[str, Any]:
    """Heatmap, active incidents, sparkline and the four stats (spec section 4.1)."""
    conn = connection_factory()
    window_start = _latest_window(conn)
    window_end = window_start + FROZEN.window_seconds
    incident_by_key = _open_incident_by_key(conn)

    stats_rows = conn.execute(
        "SELECT segment_key, attempts, failures, baseline_rate FROM segments_stats "
        "WHERE window_start = ?",
        (window_start,),
    ).fetchall()
    by_key = {str(row["segment_key"]): dict(row) for row in stats_rows}

    segments: list[dict[str, Any]] = []

    def add(key: str, method: str, instrument: str) -> None:
        row = by_key.get(key)
        if row is None:
            return
        attempts = int(row["attempts"])
        failures = int(row["failures"])
        segments.append(
            {
                "key": key,
                "method": method,
                "instrument": instrument,
                "attempts": attempts,
                "failures": failures,
                "rate": (attempts - failures) / attempts if attempts else 0.0,
                "failure_rate": failures / attempts if attempts else 0.0,
                "baseline": float(row["baseline_rate"]),
                "incident_id": incident_by_key.get(key),
            }
        )

    # The pinned merchant-wide row first.
    add(ALL_KEY, "all", "All methods")
    for method in HEATMAP_METHODS:
        add(method, method, "All")
    for key in sorted(by_key):
        method, dimension, value = parse_key(key)
        if key == ALL_KEY or dimension is None or dimension == "error_step":
            continue
        add(key, method, f"{value}")

    incidents = [_incident_summary(conn, incident) for incident in repo.open_incidents(conn)]

    series = [
        {
            "t": int(row["bucket"]),
            "attempts": int(row["attempts"]),
            "failures": int(row["failures"]),
        }
        for row in conn.execute(
            "SELECT (created_at / 900) * 900 AS bucket, COUNT(*) AS attempts, "
            "SUM(status = 'failed') AS failures FROM v_payment_attempts "
            "WHERE created_at >= ? GROUP BY bucket ORDER BY bucket",
            (window_end - 24 * 3600,),
        )
    ]

    hour = conn.execute(
        "SELECT COUNT(*) AS attempts, SUM(status = 'failed') AS failures "
        "FROM v_payment_attempts WHERE created_at >= ?",
        (window_end - 3600,),
    ).fetchone()
    attempts_last_hour = int(hour["attempts"] or 0)
    failures_last_hour = int(hour["failures"] or 0)

    recovered = conn.execute(
        "SELECT COALESCE(SUM(o.amount), 0) AS total FROM recovery_routes r "
        "JOIN v_orders o ON o.id = r.order_id WHERE r.route IN ('link', 'steer')"
    ).fetchone()

    return {
        "clock": "sim",
        "now": window_end,
        "window": {"start": window_start, "end": window_end},
        "segments": segments,
        "incidents": incidents,
        "series": series,
        "stats": {
            "attempts_last_hour": attempts_last_hour,
            "success_rate": (
                (attempts_last_hour - failures_last_hour) / attempts_last_hour
                if attempts_last_hour
                else None
            ),
            "at_risk_amount": sum(int(i["at_risk_amount"]) for i in incidents),
            "recovered_amount": int(recovered["total"]),
        },
    }


def _incident_summary(conn, incident: dict[str, Any]) -> dict[str, Any]:
    incident_id = str(incident["id"])
    cases = repo.cases_for_incident(conn, incident_id)
    recovered = conn.execute(
        "SELECT COALESCE(SUM(o.amount), 0) AS total FROM recovery_cases c "
        "JOIN v_orders o ON o.id = c.order_id WHERE c.incident_id = ? AND c.outcome = 'RECOVERED'",
        (incident_id,),
    ).fetchone()
    actions = repo.actions_for_incident(conn, incident_id)
    escalations = conn.execute(
        "SELECT COUNT(*) AS n FROM escalations WHERE incident_id = ?", (incident_id,)
    ).fetchone()["n"]
    return {
        "id": incident_id,
        "segment_key": str(incident["segment_key"]),
        "affected_scope": json.loads(incident["affected_scope_json"] or "[]"),
        "opened_at": int(incident["opened_at"]),
        "closed_at": incident["closed_at"],
        "status": str(incident["status"]),
        "rules_cause": incident["rules_cause"],
        "llm_cause": incident["llm_cause"],
        "root_cause": incident["root_cause"],
        "confidence": incident["confidence"],
        "at_risk_amount": int(incident["at_risk_amount"]),
        "recovered_amount": int(recovered["total"]),
        "cases": len(cases),
        "actions": len(actions),
        "escalated": bool(escalations),
    }


@router.get("/incidents")
def list_incidents(
    connection_factory: ConnFactory,
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """Paginated server-side at 50 rows, per spec section 2."""
    conn = connection_factory()
    rows = [
        incident
        for incident in repo.list_incidents(conn)
        if status is None or str(incident["status"]) == status
    ]
    rows.sort(key=lambda incident: int(incident["opened_at"]), reverse=True)
    page = rows[offset : offset + limit]
    return {
        "clock": "sim",
        "total": len(rows),
        "limit": limit,
        "offset": offset,
        "incidents": [_incident_summary(conn, incident) for incident in page],
    }


@router.get("/incidents/{incident_id}")
def incident_detail(incident_id: str, connection_factory: ConnFactory) -> dict[str, Any]:
    """Everything the detail page renders, in the order the page renders it (spec 4.2)."""
    conn = connection_factory()
    incident = repo.get_incident(conn, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail=f"no incident {incident_id}")

    evidence = _evidence_for(conn, incident)
    diagnosis = _diagnosis_for(conn, incident)
    plan = _plan_for(conn, incident)
    cases = [
        {
            "id": str(case["id"]),
            "order_id": str(case["order_id"]),
            "ref_hash": (repo.get_customer(conn, str(case["customer_id"])) or {}).get(
                "ref_hash", ""
            )[:12],
            "amount": int((repo.get_order(conn, str(case["order_id"])) or {}).get("amount", 0)),
            "state": str(case["state"]),
            "nudges": int(case["attempts"]),
            "link_id": case["link_id"],
            "next_action_at": case["next_action_at"],
            "outcome": case["outcome"],
        }
        for case in repo.cases_for_incident(conn, incident_id)
    ]
    timeline = [
        {
            "seq": int(row["seq"]),
            "ts": int(row["ts"]),
            "kind": str(row["kind"]),
            "ref_type": str(row["ref_type"]),
            "ref_id": str(row["ref_id"]),
            "hash": str(row["hash"])[:12],
            "payload": json.loads(row["payload_json"]),
        }
        for row in conn.execute(
            "SELECT * FROM ledger WHERE ref_id = ? OR payload_json LIKE ? ORDER BY seq",
            (incident_id, f'%"{incident_id}"%'),
        )
    ]
    return {
        "clock": "sim",
        "incident": _incident_summary(conn, incident),
        "evidence": evidence,
        "diagnosis": diagnosis,
        "plan": plan,
        "cases": cases,
        "timeline": timeline,
    }


def _evidence_for(conn, incident: dict[str, Any]) -> dict[str, Any] | None:
    """The evidence packet as it was recorded, or rebuilt if the ledger has none.

    Preferring the ledger copy matters: the page is showing what the model was actually given,
    not what the same code would produce today.
    """
    row = conn.execute(
        "SELECT payload_json FROM ledger WHERE kind = 'diagnose.reconciled' AND ref_id = ? "
        "ORDER BY seq DESC LIMIT 1",
        (str(incident["id"]),),
    ).fetchone()
    if row is not None:
        payload = json.loads(row["payload_json"])
        if payload.get("evidence"):
            return payload["evidence"]
    from salvage.diagnose.evidence import build_for_incident

    try:
        return json.loads(build_for_incident(conn, incident).model_dump_json())
    except Exception:  # noqa: BLE001 - an unrenderable packet must not break the page
        return None


def _diagnosis_for(conn, incident: dict[str, Any]) -> dict[str, Any]:
    row = conn.execute(
        "SELECT payload_json FROM ledger WHERE kind = 'diagnose.reconciled' AND ref_id = ? "
        "ORDER BY seq DESC LIMIT 1",
        (str(incident["id"]),),
    ).fetchone()
    recorded = json.loads(row["payload_json"]) if row else {}
    return {
        "rules": incident["rules_cause"],
        "llm": incident["llm_cause"],
        "reconciled": incident["root_cause"],
        "confidence": incident["confidence"],
        "agreed": recorded.get("agreed"),
        "rationale": recorded.get("rationale", ""),
        "rules_detail": recorded.get("rules_detail", ""),
        "escalate": recorded.get("escalate"),
        "escalation_reason": recorded.get("escalation_reason"),
        # The spec's "Show prompt and raw response" disclosure. Absent when no model ran, which is
        # the current state of the agent arm and is shown as such rather than as an empty box.
        "prompt": recorded.get("prompt"),
        "raw_response": recorded.get("raw_response"),
    }


def _plan_for(conn, incident: dict[str, Any]) -> dict[str, Any]:
    plan = json.loads(incident["plan_json"] or "{}")
    actions = [
        {
            "id": str(row["id"]),
            "type": str(row["type"]),
            "case_id": row["case_id"],
            "status": str(row["status"]),
            "params": json.loads(row["params_json"] or "{}"),
            "gate": json.loads(row["gate_json"] or "[]"),
            "executed_at": row["executed_at"],
        }
        for row in conn.execute(
            "SELECT * FROM actions WHERE incident_id = ? ORDER BY id", (str(incident["id"]),)
        )
    ]
    return {
        "proposed": plan.get("actions", []),
        "rationale": plan.get("rationale", ""),
        "actions": actions,
    }


@router.post("/incidents/{incident_id}/close", dependencies=[Depends(require_token)])
def close_incident(incident_id: str, connection_factory: ConnFactory) -> dict[str, Any]:
    conn = connection_factory()
    incident = repo.get_incident(conn, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail=f"no incident {incident_id}")
    if incident["closed_at"] is not None:
        return {"id": incident_id, "closed_at": int(incident["closed_at"]), "already": True}

    now = _latest_window(conn) + FROZEN.window_seconds
    repo.close_incident(conn, incident_id, now)
    BUS.publish("incident.closed", {"id": incident_id, "closed_at": now})
    return {"id": incident_id, "closed_at": now, "already": False}
