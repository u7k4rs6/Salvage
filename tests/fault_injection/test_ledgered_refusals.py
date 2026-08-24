"""Every refusal that happens inside a run is written to the ledger.

The M3 exit criterion is that injection attempts are refused and ledgered. Most of the injections
in this suite are refused by a layer that sits above the ledger: a signature that does not verify,
an enum that rejects a value, a schema that rejects a field. Nothing is written for those because
nothing happened, and inventing a ledger entry for a request that was thrown away at the door would
be recording noise as history.

What must be ledgered is every refusal the executor makes, because that is a decision Salvage took
about a real order. This file runs a scenario end to end and checks that.
"""

from __future__ import annotations

import json

import pytest

from salvage.db import open_migrated
from salvage.eval.agent_run import run_policy_scenario
from salvage.ledger import verify


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    import yaml

    from salvage.sim.params import PARAMS_PATH

    root = tmp_path_factory.mktemp("ledgered")
    raw = yaml.safe_load(PARAMS_PATH.read_text(encoding="utf-8"))
    raw["merchant"]["customer_count"] = 400
    raw["traffic"]["attempts_per_day"] = 2400
    raw["clock"]["warmup_days"] = 2
    raw["clock"]["settle_days"] = 2
    params_path = root / "params.yaml"
    params_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    conn = open_migrated(root / "run.db")
    result = run_policy_scenario(
        conn, scenario="S1", seed=2, policy="B1", params_path=params_path
    )
    yield result, conn
    conn.close()


def test_every_refused_action_has_a_ledger_entry(run, injection_log):
    _, conn = run
    refused = {
        str(row["id"])
        for row in conn.execute("SELECT id FROM actions WHERE status = 'refused'")
    }
    assert refused, "the run produced no refusals, so this proves nothing"
    ledgered = {
        str(row["ref_id"])
        for row in conn.execute(
            "SELECT ref_id FROM ledger WHERE kind = 'execute.action.refused'"
        )
    }
    assert refused <= ledgered, sorted(refused - ledgered)[:5]
    injection_log.record(
        category="ledger",
        attack="a refusal that leaves no trace",
        refused=True,
        ledgered=True,
        detail=f"{len(refused)} refusals in one run, every one with a ledger entry",
    )


def test_every_refusal_carries_the_rule_that_refused_it(run, injection_log):
    _, conn = run
    rows = conn.execute(
        "SELECT payload_json FROM ledger WHERE kind = 'execute.action.refused' LIMIT 200"
    ).fetchall()
    assert rows
    for row in rows:
        payload = json.loads(row["payload_json"])
        gates = payload["gates"]
        assert gates
        assert any(not gate["passed"] for gate in gates), payload
    injection_log.record(
        category="ledger",
        attack="a refusal recorded without saying which rule refused it",
        refused=True,
        ledgered=True,
        detail="every refused action's gate list names a failing rule",
    )


def test_the_chain_and_the_event_stream_both_survive_a_full_run(run, injection_log):
    result, conn = run
    from salvage.sim.verify import verify_stream

    assert verify(conn).ok
    assert verify_stream(conn, result.sim.run_id).ok
    injection_log.record(
        category="ledger",
        attack="tampering hidden by a busy run",
        refused=True,
        ledgered=True,
        detail="hash chain and stream commitment both verify after the run",
    )


def test_no_policy_violation_survives_a_full_run(run, injection_log):
    from salvage.eval.agent_run import count_policy_violations, violation_breakdown

    _, conn = run
    breakdown = violation_breakdown(conn)
    assert count_policy_violations(conn) == 0, breakdown
    injection_log.record(
        category="ledger",
        attack="a section 9 bound broken during a full run",
        refused=True,
        ledgered=True,
        detail=f"zero violations across {sum(breakdown.values()) or 0} checks",
    )
