"""Results routes.

docs/04_FRONTEND_SPEC.md section 4.5: the page renders the same structure the evaluation runner
writes to data/results/<run_id>.json, so this serves those files rather than recomputing anything.
A number on the Results page and a number in docs/RESULTS.md come from one source.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from salvage.eval.report import load_json
from salvage.eval.sweep import aggregate

router = APIRouter(prefix="/api/results", tags=["results"])

RESULTS_DIR = Path("data/results")
# Files that are sweep artefacts rather than policy runs. Listed so the run selector does not
# offer them as if they were.
SIDECARS = {"fault_injection", "volume_sweep", "sensitivity", "diagnosis", "offpeak"}


def _runs() -> list[dict[str, Any]]:
    if not RESULTS_DIR.exists():
        return []
    runs = []
    for path in sorted(RESULTS_DIR.glob("*.json")):
        if path.stem in SIDECARS:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if "rows" not in payload or "policies" not in payload:
            continue
        rows = payload.get("rows", [])
        # A sweep row names one run: one scenario, one seed, one policy. A sweep artefact like the
        # steer or escalation-fix curve also has "rows" and "policies", but its rows are already
        # aggregated over seeds, and reading one as a run took the whole page down with a KeyError
        # the first time such an artefact was written. Shape, not filename: SIDECARS above is a
        # list somebody has to remember to update, and this is not.
        if not all(
            isinstance(row, dict) and {"scenario", "seed", "policy"} <= row.keys() for row in rows
        ):
            continue
        # Derived from the rows rather than read from the file's own header. A merge or an
        # interrupted shard can leave a header that does not describe its rows, and the run
        # selector is the one place where that would be invisible.
        runs.append(
            {
                "run_id": payload.get("run_id", path.stem),
                "scenarios": sorted({row["scenario"] for row in rows}),
                "seeds": sorted({row["seed"] for row in rows}),
                "policies": list(dict.fromkeys(row["policy"] for row in rows)),
                "variant": payload.get("variant", "peak"),
                "finished_at": payload.get("finished_at", 0),
                "runs": len(payload.get("rows", [])),
            }
        )
    runs.sort(key=lambda run: run["finished_at"], reverse=True)
    return runs


@router.get("")
def list_runs() -> dict[str, Any]:
    runs = _runs()
    return {
        "runs": runs,
        "latest": runs[0]["run_id"] if runs else None,
        # The page must say plainly when a column is not a measurement. Read from the report
        # module rather than duplicated, so the two cannot drift.
        "notes": _notes(),
    }


def _notes() -> list[str]:
    from salvage.llm.provider import FIXTURE_DIR

    notes: list[str] = []
    if not list(FIXTURE_DIR.glob("*.json")):
        notes.append(
            "The agent arm ran with no diagnosis model, so it took no customer-facing action and "
            "its column equals B0. See docs/RESULTS.md."
        )
    return notes


@router.get("/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    payload = load_json(RESULTS_DIR / f"{run_id}.json")
    if payload is None:
        raise HTTPException(status_code=404, detail=f"no results run {run_id}")

    from salvage.eval.report import rows_from_json

    result = rows_from_json(payload)
    # A results file written before the at-risk metrics existed has no at-risk fields, and the
    # metrics dataclass would default them to zero. A zero that means "not measured" reading as
    # "recovered nothing" is exactly the kind of quiet wrong number this project keeps finding,
    # so the page is told and the columns are suppressed rather than rendered as zeros.
    at_risk_measured = all("at_risk_orders" in row for row in payload.get("rows", []))
    aggregates = [
        {
            "scenario": row.scenario,
            "policy": row.policy,
            "seeds": row.seeds,
            "at_risk_orders": row.mean_at_risk_orders,
            "at_risk_amount": row.mean_at_risk_amount,
            "at_risk_recovered_amount": row.mean_at_risk_recovered_amount,
            "at_risk_recovery_rate": row.mean_at_risk_recovery_rate,
            "at_risk_messages": row.mean_at_risk_messages,
            "recovered_amount": row.mean_recovered_amount,
            "recovered_std": row.std_recovered_amount,
            "recovery_rate": row.mean_recovery_rate,
            "messages": row.mean_messages,
            "opt_outs": row.mean_opt_outs,
            "contacts_per_1000": row.mean_contacts_per_1000,
            "escalations": row.mean_escalations,
            "detected": row.detected,
            "time_to_detect": row.mean_time_to_detect,
            "violations": row.total_violations,
            "link_orders": row.mean_link_orders,
            "steer_orders": row.mean_steer_orders,
            "organic_orders": row.mean_organic_orders,
        }
        for row in aggregate(result.rows)
    ]
    identical = all(len(set(d.values())) <= 1 for d in result.digests.values())
    notes = _notes() + list(result.notes)
    if not at_risk_measured:
        notes.append(
            "This run predates the at-risk order set, so its at-risk columns are not measured "
            "and are not shown. Re-run `salvage eval run` to populate them."
        )
    return {
        "run_id": result.run_id,
        "scenarios": sorted({row.scenario for row in result.rows}),
        "seeds": sorted({row.seed for row in result.rows}),
        "policies": list(dict.fromkeys(row.policy for row in result.rows)),
        "at_risk_measured": at_risk_measured,
        "variant": result.variant,
        "aggregates": aggregates,
        "worlds": len(result.digests),
        "worlds_identical": identical,
        "violations": sum(row.policy_violations for row in result.rows),
        "notes": notes,
        "diagnosis": load_json(RESULTS_DIR / "diagnosis.json"),
        "volume_sweep": load_json(RESULTS_DIR / "volume_sweep.json"),
        "sensitivity": load_json(RESULTS_DIR / "sensitivity.json"),
        "fault_injection": load_json(RESULTS_DIR / "fault_injection.json"),
    }
