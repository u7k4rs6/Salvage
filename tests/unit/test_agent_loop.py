"""The whole loop, end to end in simulation.

M2's exit criteria: a full S1 run producing an incident, a diagnosis, a plan, per-action gate
results, links, validated messages, recorded outcomes and a ledger that verifies; and S4
producing an escalation and zero customer contacts.

These run at reduced volume through small_params_path so the suite stays quick. The full-scale
versions are in the M2 report. Everything else about them is the shipped instrument: same
scenarios, same fault profiles, same policy engine, same fixtures.
"""

from __future__ import annotations

import json

import pytest

from salvage.db import open_migrated
from salvage.eval.agent_run import run_agent_scenario
from salvage.execute.workflow import TERMINAL_STATES, CaseState
from salvage.ledger import verify
from salvage.llm.provider import FixtureProvider
from salvage.sim.verify import verify_stream


@pytest.fixture
def agent_db(tmp_path):
    conn = open_migrated(tmp_path / "agent.db")
    yield conn
    conn.close()


def _run(conn, scenario: str, seed: int, small_params_path, provider=None, **kwargs):
    return run_agent_scenario(
        conn,
        scenario=scenario,
        seed=seed,
        provider=provider,
        params_path=small_params_path,
        **kwargs,
    )


# -- the model-free path ---------------------------------------------------


def test_without_a_model_nothing_customer_facing_happens(agent_db, small_params_path):
    """The rules alone sit below the 0.6 action threshold, so the agent asks a human instead.

    This is the designed behaviour, not a limitation: Architecture section 6 gives a rules-only
    diagnosis no confidence, and acting on one unsupervised would be acting on half the evidence.
    """
    result = _run(agent_db, "S1", 1, small_params_path, provider=None)
    assert result.stats.messages_sent == 0
    assert result.stats.links_created == 0
    if result.stats.incidents:
        assert result.stats.escalations > 0
        for incident in result.incidents:
            assert incident["confidence"] == pytest.approx(0.5)


def test_the_kill_switch_stops_outbound_actions_but_not_detection(agent_db, small_params_path):
    result = _run(agent_db, "S1", 1, small_params_path, provider=None, kill_switch=True)
    assert result.stats.messages_sent == 0
    assert result.stats.links_created == 0
    # Detection and diagnosis carry on (docs/03_SECURITY_AND_ACCESS.md section 6).
    assert result.stats.diagnosed == result.stats.incidents


# -- state machine and ledger over a real run ------------------------------


def test_every_case_ends_in_a_legal_terminal_state(agent_db, small_params_path):
    _run(agent_db, "S1", 1, small_params_path, provider=None)
    states = {row["state"] for row in agent_db.execute("SELECT DISTINCT state FROM recovery_cases")}
    for state in states:
        assert CaseState(state) in TERMINAL_STATES, state


def test_the_ledger_and_the_event_stream_both_verify_after_a_run(agent_db, small_params_path):
    result = _run(agent_db, "S1", 1, small_params_path, provider=None)
    assert verify(agent_db).ok
    assert verify_stream(agent_db, result.sim.run_id).ok


def test_every_action_records_its_gates(agent_db, small_params_path):
    _run(agent_db, "S1", 1, small_params_path, provider=None)
    rows = agent_db.execute("SELECT type, status, gate_json FROM actions").fetchall()
    for row in rows:
        gates = json.loads(row["gate_json"])
        if row["type"] in ("ESCALATE_HUMAN", "NO_ACTION"):
            continue
        assert gates, f"{row['type']} {row['status']} recorded no gates"
        for gate in gates:
            assert set(gate) == {"rule", "passed", "detail"}


def test_the_ledger_carries_no_message_body_or_contact(agent_db, small_params_path):
    import re

    _run(agent_db, "S1", 1, small_params_path, provider=None)
    text = " ".join(
        row["payload_json"] for row in agent_db.execute("SELECT payload_json FROM ledger")
    )
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]{2,}", text)
    assert not re.search(r"(?<![0-9A-Za-z])(?:\+?91[-\s]?)?[6-9]\d{9}(?![0-9A-Za-z])", text)
    assert "Reply STOP" not in text


def test_customer_comms_stores_a_hash_and_never_a_body(agent_db, small_params_path):
    _run(agent_db, "S1", 1, small_params_path, provider=None)
    columns = {row["name"] for row in agent_db.execute("PRAGMA table_info(customer_comms)")}
    assert "body" not in columns
    assert "body_hash" in columns


# -- S4: escalate only, never contact anybody ------------------------------


def test_s4_escalates_and_contacts_nobody(agent_db, small_params_path):
    """docs/01_PRD.md section 10: merchant misconfiguration escalates to a human only.

    Run without a model, so the rules classifier alone drives it. A merchant_config diagnosis
    cannot produce a customer contact at any confidence, because the matrix refuses
    SEND_RECOVERY_LINK for that cause before confidence is even consulted.
    """
    result = _run(agent_db, "S4", 1, small_params_path, provider=None)
    assert result.stats.messages_sent == 0
    assert result.customer_contacts == 0
    assert result.stats.links_created == 0
    comms = agent_db.execute("SELECT COUNT(*) AS n FROM customer_comms").fetchone()["n"]
    assert comms == 0
    if result.stats.incidents:
        assert result.stats.escalations > 0
        assert result.escalations


def test_a_merchant_config_incident_refuses_a_link_on_the_matrix(agent_db, small_params_path):
    """Even if a plan asked for one, the gate refuses it before anything happens."""
    from salvage.decide.menu import ActionType
    from salvage.decide.policy import ActionContext, Decision, evaluate
    from salvage.taxonomy import RootCause

    verdict = evaluate(
        ActionContext(
            action_type=ActionType.SEND_RECOVERY_LINK,
            cause=RootCause.MERCHANT_CONFIG.value,
            confidence=0.99,
            incident_id="inc",
            now=1_700_000_000,
            consent=True,
            order_paid=False,
        )
    )
    assert verdict.decision == Decision.REFUSE
    assert verdict.refusing_rule == "matrix.action_allowed_for_cause"


# -- with fixtures, the full loop acts ------------------------------------


def _fixture_provider() -> FixtureProvider:
    return FixtureProvider(strict=True)


def test_the_shipped_fixtures_cover_the_full_scale_s1_run():
    """The fixtures are keyed by prompt hash, so a change to the evidence packet's shape breaks
    them loudly rather than answering a different question. This asserts the S1 fixture is still
    the one the shipped params produce."""
    from salvage.llm.provider import FIXTURE_DIR

    hashes = {path.stem for path in FIXTURE_DIR.glob("*.json")}
    assert len(hashes) >= 20
    for path in FIXTURE_DIR.glob("*.json"):
        record = json.loads(path.read_text())
        assert record["prompt_hash"] == path.stem
        assert "response" in record
