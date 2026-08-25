"""The dashboard's route surface.

docs/04_FRONTEND_SPEC.md section 5 lists the routes; docs/03_SECURITY_AND_ACCESS.md section 9
fixes who may call them. These tests are about the contract the pages are written against: shape,
the token gate, CORS, and the two places where an empty database has to produce an empty page
rather than a 500. Page behaviour lives in the frontend; this is the seam.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from salvage import repo
from salvage.api import deps
from salvage.api.app import ALLOWED_ORIGINS, create_app
from salvage.config import get_settings, reset_settings_cache
from salvage.db import open_migrated
from salvage.ledger import GENESIS_HASH, Ledger

TOKEN = "test-dashboard-token"


@pytest.fixture
def client(tmp_path, monkeypatch):
    """An app wired to an empty migrated database and a known token."""
    db_path = tmp_path / "api.db"
    open_migrated(db_path).close()
    monkeypatch.setenv("SALVAGE_DASHBOARD_TOKEN", TOKEN)
    monkeypatch.setenv("SALVAGE_DB_PATH", str(db_path))
    monkeypatch.setenv("SALVAGE_ENV", "dev")
    reset_settings_cache()

    app = create_app()

    def factory():
        return open_migrated(db_path)

    app.dependency_overrides[deps.get_connection_factory] = lambda: factory
    with TestClient(app) as test_client:
        test_client.db_path = db_path
        yield test_client
    reset_settings_cache()


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


# ---------------------------------------------------------------------------
# Empty database
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/api/health",
        "/api/overview",
        "/api/incidents",
        "/api/escalations",
        "/api/ledger",
        "/api/results",
        "/api/sim/status",
        "/api/control/status",
        "/api/storefront/skus",
        "/api/storefront/checkout-config",
    ],
)
def test_read_routes_answer_on_an_empty_database(client, path):
    """Every page has a mandatory empty state (frontend spec section 2), and an empty state is
    only reachable if the route returns a body instead of a 500."""
    response = client.get(path)
    assert response.status_code == 200, response.text
    assert isinstance(response.json(), dict)


def seed_window(conn, window_start: int) -> None:
    """One detector window with the merchant-wide row and two method rows."""
    for key, attempts, failures in (("all", 900, 90), ("upi", 400, 80), ("card", 300, 6)):
        repo.upsert_segment_stat(
            conn,
            {
                "segment_key": key,
                "window_start": window_start,
                "attempts": attempts,
                "failures": failures,
                "baseline_rate": 0.05,
                "p_value": 1.0,
            },
        )
    conn.commit()


def test_overview_pins_the_merchant_wide_row_first(client):
    """The decision recorded in BUILD_LOG under M2: `all` is pinned at the top of the heatmap so
    a reader sees the merchant number before the segment breakdown. It is pinned by position, not
    by sorting on a rate, so a healthy merchant-wide row does not sink below a broken segment."""
    conn = open_migrated(client.db_path)
    seed_window(conn, 1_780_000_000)
    body = client.get("/api/overview").json()
    assert [segment["key"] for segment in body["segments"]][:3] == ["all", "upi", "card"]


def test_overview_returns_an_empty_heatmap_before_the_first_window(client):
    """No attempts yet is an empty state, not a fabricated zero row."""
    assert client.get("/api/overview").json()["segments"] == []


def test_incident_detail_404s_rather_than_inventing_one(client):
    assert client.get("/api/incidents/inc_does_not_exist").status_code == 404


# ---------------------------------------------------------------------------
# The token gate
# ---------------------------------------------------------------------------

MUTATING = [
    ("POST", "/api/incidents/inc_x/close", {}),
    ("POST", "/api/escalations/esc_x/decision", {"decision": "approve", "note": "n"}),
    ("POST", "/api/sim/run", {"scenario": "S1", "seed": 0}),
    ("POST", "/api/sim/stop", {}),
    ("POST", "/api/control/kill-switch", {"enabled": True}),
    ("POST", "/api/storefront/simulate-failure", {}),
]


@pytest.mark.parametrize(("method", "path", "body"), MUTATING)
def test_mutating_routes_refuse_without_a_token(client, method, path, body):
    response = client.request(method, path, json=body)
    assert response.status_code == 401, f"{path} answered {response.status_code}"


@pytest.mark.parametrize(("method", "path", "body"), MUTATING)
def test_mutating_routes_refuse_the_wrong_token(client, method, path, body):
    response = client.request(method, path, json=body, headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 403, f"{path} answered {response.status_code}"


def test_an_unset_token_closes_every_mutating_route(client, monkeypatch):
    """Not the reverse. A deployment that forgot to set a token is not one where the kill switch
    is open to anyone on the machine."""
    monkeypatch.delenv("SALVAGE_DASHBOARD_TOKEN", raising=False)
    reset_settings_cache()
    response = client.post("/api/control/kill-switch", json={"enabled": True})
    assert response.status_code == 503
    assert "SALVAGE_DASHBOARD_TOKEN" in response.json()["detail"]


def test_read_routes_stay_open_on_loopback(client):
    """The bind address is the access control for reads (security doc section 9)."""
    assert client.get("/api/ledger").status_code == 200
    assert client.get("/api/overview").status_code == 200


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------


def test_cors_allows_the_vite_origin_only(client):
    allowed = client.get("/api/overview", headers={"Origin": ALLOWED_ORIGINS[0]})
    assert allowed.headers.get("access-control-allow-origin") == ALLOWED_ORIGINS[0]

    other = client.get("/api/overview", headers={"Origin": "http://evil.example"})
    # Starlette answers the request but does not stamp the header, so the browser drops the body.
    assert "access-control-allow-origin" not in other.headers


# ---------------------------------------------------------------------------
# Behaviour that the pages depend on
# ---------------------------------------------------------------------------


def test_kill_switch_flips_the_setting_and_lands_in_the_ledger(client):
    response = client.post("/api/control/kill-switch", json={"enabled": True}, headers=auth())
    assert response.status_code == 200
    assert get_settings().salvage_kill_switch is True
    assert client.get("/api/control/status").json()["kill_switch"] is True

    conn = open_migrated(client.db_path)
    entries = list(Ledger(conn).iter_entries(kind="control.kill_switch"))
    assert [json.loads(e.payload_json)["enabled"] for e in entries] == [True]

    client.post("/api/control/kill-switch", json={"enabled": False}, headers=auth())
    assert get_settings().salvage_kill_switch is False


def test_a_dashboard_run_cannot_opt_out_of_the_kill_switch(client, monkeypatch):
    """The rehearsal found this one: the runner built its own arguments and never read the
    switch, so a run started after an operator flipped it would have sent anyway. The kill
    switch is an operator control, so it is read from settings and is not a run option."""
    from salvage.api import routes_sim

    seen: dict[str, object] = {}

    def fake_run(conn, **kwargs):
        seen.update(kwargs)
        raise RuntimeError("stop here, the arguments are the point")

    monkeypatch.setattr("salvage.eval.agent_run.run_policy_scenario", fake_run)
    monkeypatch.setattr("salvage.demo.reset", lambda conn, **kw: {})

    client.post("/api/control/kill-switch", json={"enabled": True}, headers=auth())
    try:
        with pytest.raises(RuntimeError):
            routes_sim._run_scenario(  # noqa: SLF001
                lambda: open_migrated(client.db_path),
                routes_sim.SimRequest(scenario="S1", seed=0, policy="B1"),
            )
        assert seen["kill_switch"] is True
    finally:
        client.post("/api/control/kill-switch", json={"enabled": False}, headers=auth())

    assert "kill_switch" not in routes_sim.SimRequest.model_fields


def test_escalation_decision_requires_a_note(client):
    """Frontend spec section 4.4: approving without a reason is how an audit trail becomes
    decoration, so the note is required by the schema rather than by the form."""
    response = client.post(
        "/api/escalations/esc_x/decision",
        json={"decision": "approve", "note": ""},
        headers=auth(),
    )
    assert response.status_code == 422


def test_ledger_verify_answers_on_an_empty_chain(client):
    body = client.post("/api/ledger/verify").json()
    assert body["ok"] is True
    assert body["entries"] == 0
    assert "does not prove" in body["proves"].lower()


def test_ledger_export_is_jsonl(client):
    conn = open_migrated(client.db_path)
    Ledger(conn).append("detect.incident.opened", "incident", "inc_1", {"a": 1}, ts=1000)
    response = client.get("/api/ledger/export")
    assert response.headers["content-type"].startswith("text/plain")
    lines = [line for line in response.text.splitlines() if line]
    # First line is the manifest carrying the genesis hash, so an exported file can be checked
    # against the chain it came from rather than trusted because it looks like a ledger.
    manifest = json.loads(lines[0])
    assert manifest["type"] == "salvage.ledger.export"
    assert manifest["genesis_hash"] == GENESIS_HASH
    assert len(lines) == 2
    assert json.loads(lines[1])["kind"] == "detect.incident.opened"


def test_storefront_says_why_it_cannot_take_an_order(client):
    """No Razorpay key configured. The page must say so instead of opening a checkout that
    cannot work."""
    body = client.get("/api/storefront/skus").json()
    assert body["available"] is False
    assert "RAZORPAY_KEY_ID" in body["reason"]
    assert client.post("/api/storefront/order", json={"sku": "kettle"}).status_code == 503


def test_simulate_failure_is_dev_only(client, monkeypatch):
    assert client.post("/api/storefront/simulate-failure", headers=auth()).status_code == 200

    monkeypatch.setenv("SALVAGE_ENV", "demo")
    reset_settings_cache()
    assert client.post("/api/storefront/simulate-failure", headers=auth()).status_code == 404


def test_one_simulation_at_a_time(client, monkeypatch):
    """Frontend spec section 4.7. Two runs against one database interleave two worlds, so the
    lock is here rather than in the form."""
    from salvage.api import routes_sim

    assert routes_sim.STATE.lock.acquire(blocking=False)
    try:
        routes_sim.STATE.running = True
        response = client.post("/api/sim/run", json={"scenario": "S1", "seed": 0}, headers=auth())
        assert response.status_code == 409
    finally:
        routes_sim.STATE.running = False
        routes_sim.STATE.lock.release()


def test_sim_run_rejects_a_scenario_that_does_not_exist(client):
    response = client.post("/api/sim/run", json={"scenario": "S9", "seed": 0}, headers=auth())
    assert response.status_code == 422


def test_incident_close_needs_an_incident(client):
    assert client.post("/api/incidents/inc_missing/close", headers=auth()).status_code == 404


def test_overview_counts_what_the_top_bar_shows(client):
    """One open incident should reach the Overview without a page-specific query path."""
    now = 1_780_000_000
    conn = open_migrated(client.db_path)
    repo.insert_incident(
        conn,
        {
            "id": "inc_api_1",
            "segment_key": "method:upi",
            "opened_at": now,
            "closed_at": None,
            "at_risk_amount": 250000,
            "status": "open",
            "affected_scope_json": "[]",
        },
    )
    conn.commit()
    body = client.get("/api/overview").json()
    assert [item["id"] for item in body["incidents"]] == ["inc_api_1"]
    assert body["stats"]["at_risk_amount"] == 250000
    assert set(body["stats"]) == {
        "attempts_last_hour",
        "success_rate",
        "at_risk_amount",
        "recovered_amount",
    }


# ---------------------------------------------------------------------------
# The event bus behind GET /api/stream
# ---------------------------------------------------------------------------


def test_bus_refuses_an_event_name_the_frontend_does_not_handle():
    """A name outside the spec's set is a typo that would silently never reach a page."""
    from salvage.api.stream import EventBus, UnknownEvent

    with pytest.raises(UnknownEvent):
        EventBus().publish("incident.reopened", {})


def test_bus_drops_the_oldest_rather_than_blocking_the_simulator():
    """A tab that stops reading must not stall the run producing the events."""
    import asyncio

    from salvage.api.stream import QUEUE_SIZE, EventBus

    async def scenario():
        bus = EventBus()
        queue = bus.subscribe()
        for index in range(QUEUE_SIZE + 5):
            bus.publish("sim.tick", {"n": index})
        assert queue.qsize() == QUEUE_SIZE
        assert bus.dropped == 5
        first = await queue.get()
        assert first["data"]["n"] == 5

    asyncio.run(scenario())
