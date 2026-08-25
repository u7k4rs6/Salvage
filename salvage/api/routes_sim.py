"""Scenario runner, storefront and the kill switch.

docs/04_FRONTEND_SPEC.md sections 4.6 and 4.7, and section 3 for the kill switch.

Only one simulation runs at a time (spec section 4.7: "only one run at a time; the form disables
while a run is active and says so"). That is enforced here with a lock rather than left to the
form, because a second run against the same database would interleave two worlds.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from salvage import repo
from salvage.api.deps import ConnFactory, require_token
from salvage.api.stream import BUS
from salvage.config import get_settings

router = APIRouter(prefix="/api", tags=["sim"])


@dataclass
class SimState:
    """What the Scenario Runner polls."""

    running: bool = False
    scenario: str | None = None
    seed: int | None = None
    policy: str | None = None
    started_at: int = 0
    finished_at: int = 0
    error: str | None = None
    stop_requested: bool = False
    summary: dict[str, Any] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def as_dict(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "scenario": self.scenario,
            "seed": self.seed,
            "policy": self.policy,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "stop_requested": self.stop_requested,
            "summary": self.summary,
        }


STATE = SimState()


class SimRequest(BaseModel):
    model_config = {"extra": "forbid"}

    scenario: str = Field(pattern="^S[0-5]$")
    seed: int = Field(ge=0, le=999)
    policy: Literal["agent", "B0", "B1", "B2"] = "agent"
    variant: Literal["peak", "offpeak"] = "peak"
    # Paced runs exist for the pitch: the spec offers "as fast as possible, or paced at N sim
    # minutes per real second". Pacing is applied by the SSE tick loop, not by slowing the
    # simulator, so the numbers a paced run produces are identical to a fast one.
    speed: int = Field(default=0, ge=0, le=600)
    # A scenario is a whole world, and two worlds in one database collide on the first customer
    # they share. The runner resets by default; unset this only to inspect a failure.
    reset: bool = True


@router.get("/sim/status")
def sim_status() -> dict[str, Any]:
    return STATE.as_dict()


@router.post("/sim/run", dependencies=[Depends(require_token)])
async def sim_run(request: SimRequest, connection_factory: ConnFactory) -> dict[str, Any]:
    if not STATE.lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail=f"a run is already active: {STATE.scenario} seed {STATE.seed}",
        )
    STATE.running = True
    STATE.scenario, STATE.seed, STATE.policy = request.scenario, request.seed, request.policy
    STATE.started_at, STATE.finished_at = int(time.time()), 0
    STATE.error, STATE.stop_requested, STATE.summary = None, False, {}

    try:
        summary = await run_in_threadpool(_run_scenario, connection_factory, request)
        STATE.summary = summary
        BUS.publish("sim.finished", summary)
        return summary
    except Exception as exc:  # noqa: BLE001 - the page must show the failure, not a blank panel
        STATE.error = str(exc)
        BUS.publish("sim.finished", {"error": str(exc)})
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        STATE.running = False
        STATE.finished_at = int(time.time())
        STATE.lock.release()


def _run_scenario(connection_factory, request: SimRequest) -> dict[str, Any]:
    from salvage.demo import reset as reset_database
    from salvage.eval.agent_run import run_policy_scenario
    from salvage.llm.provider import build_provider

    settings = get_settings()
    provider = None
    if request.policy == "agent" and settings.salvage_llm_provider != "fixture":
        provider = build_provider(settings.salvage_llm_provider)
    elif request.policy == "agent":
        from salvage.llm.provider import FIXTURE_DIR

        if list(FIXTURE_DIR.glob("*.json")):
            provider = build_provider("fixture")

    conn = connection_factory()
    if request.reset:
        reset_database(conn)
    result = run_policy_scenario(
        conn,
        scenario=request.scenario,
        seed=request.seed,
        policy=request.policy,
        variant=request.variant,
        provider=provider,
        # Read from settings rather than from the request: the kill switch is an operator
        # control, not a run option, and a run must not be able to opt out of it. Settings are
        # re-read here because the flip resets the cache, so a run started after the flip sees
        # it without a restart.
        kill_switch=settings.salvage_kill_switch,
    )
    metrics = result.metrics
    BUS.publish(
        "sim.tick",
        {"scenario": request.scenario, "seed": request.seed, "attempts": result.sim.attempts},
    )
    for incident in result.incidents:
        BUS.publish(
            "incident.opened",
            {"id": str(incident["id"]), "segment_key": str(incident["segment_key"])},
        )
    for escalation in result.escalations:
        BUS.publish(
            "escalation.opened",
            {"id": str(escalation["id"]), "incident_id": str(escalation["incident_id"])},
        )
    return {
        "run_id": result.sim.run_id,
        "scenario": request.scenario,
        "seed": request.seed,
        "policy": request.policy,
        "variant": request.variant,
        "attempts": result.sim.attempts,
        "orders": result.sim.orders,
        "incidents": metrics.incidents,
        "escalations": metrics.escalations,
        "actions_executed": result.stats.actions_executed,
        "actions_refused": result.stats.actions_refused,
        "links_created": metrics.links_created,
        "messages_sent": metrics.messages_sent,
        "opt_outs": metrics.opt_outs,
        "at_risk_orders": metrics.at_risk_orders,
        "at_risk_recovered_orders": metrics.at_risk_recovered_orders,
        "at_risk_recovered_amount": metrics.at_risk_recovered_amount,
        "recovered_amount": metrics.recovered_amount,
        "policy_violations": metrics.policy_violations,
        "provider": "none" if provider is None else provider.name,
        "reset": request.reset,
        "kill_switch": settings.salvage_kill_switch,
    }


@router.post("/sim/stop", dependencies=[Depends(require_token)])
def sim_stop() -> dict[str, Any]:
    """Record that the operator asked the current run to stop.

    Being honest about what this does: a scenario is seconds of work in one thread, so there is
    no safe interruption point that would not leave a half written world. The flag is surfaced
    in the status payload so the page can say "stopping" and refuse to queue another run; the
    current run still finishes. Killing a run mid transaction is the kill switch's job, and the
    kill switch stops outbound calls rather than the simulation.
    """
    STATE.stop_requested = True
    return {"running": STATE.running, "stop_requested": True}


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------


class KillSwitch(BaseModel):
    model_config = {"extra": "forbid"}

    enabled: bool


@router.post("/control/kill-switch", dependencies=[Depends(require_token)])
def kill_switch(request: KillSwitch, connection_factory: ConnFactory) -> dict[str, Any]:
    """Suspend or resume outbound actions.

    docs/03_SECURITY_AND_ACCESS.md section 6: the switch is checked at the start of every
    executor tick, and when set no outbound call is made while detection and diagnosis
    continue. The environment variable is the source of truth for a fresh process; this sets
    it for the running one and ledgers the change, because flipping it is an operator decision
    and the audit trail should say who suspended the agent and when.
    """
    import os

    from salvage.config import reset_settings_cache
    from salvage.ledger import Ledger

    os.environ["SALVAGE_KILL_SWITCH"] = "1" if request.enabled else "0"
    reset_settings_cache()
    now = int(time.time())
    Ledger(connection_factory()).append(
        "control.kill_switch",
        "control",
        "kill_switch",
        {"enabled": request.enabled, "source": "dashboard"},
        ts=now,
    )
    return {"enabled": request.enabled, "at": now}


@router.get("/control/status")
def control_status() -> dict[str, Any]:
    """What the top bar renders: environment, clock, kill switch, active incident count."""
    settings = get_settings()
    return {
        "env": settings.salvage_env,
        "kill_switch": settings.salvage_kill_switch,
        "llm_provider": settings.salvage_llm_provider,
    }


# ---------------------------------------------------------------------------
# Storefront
# ---------------------------------------------------------------------------

SKUS = [
    {"sku": "kettle", "name": "Steel Kettle", "amount": 129900},
    {"sku": "kurta", "name": "Cotton Kurta", "amount": 249900},
    {"sku": "rug", "name": "Jute Rug", "amount": 589900},
]


class OrderRequest(BaseModel):
    model_config = {"extra": "forbid"}

    sku: str


@router.get("/storefront/skus")
def storefront_skus() -> dict[str, Any]:
    settings = get_settings()
    return {
        "skus": SKUS,
        "key_id": settings.razorpay_key_id,
        # The page must degrade honestly rather than opening a checkout that cannot work.
        "available": bool(settings.razorpay_key_id and settings.razorpay_key_secret),
        "reason": (
            ""
            if settings.razorpay_key_id
            else "RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET are not set, so no real order can be "
            "created. Fill them in .env and restart."
        ),
    }


@router.post("/storefront/order")
def storefront_order(request: OrderRequest, connection_factory: ConnFactory) -> dict[str, Any]:
    """Create a real test-mode Order and return the checkout options."""
    from salvage.config import ConfigError
    from salvage.execute.razorpay_client import RazorpayClient, RazorpayError

    sku = next((item for item in SKUS if item["sku"] == request.sku), None)
    if sku is None:
        raise HTTPException(status_code=404, detail=f"no sku {request.sku}")

    settings = get_settings()
    try:
        client = RazorpayClient(settings=settings)
    except ConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        response = client.create_order(
            amount=int(sku["amount"]), receipt=f"store_{int(time.time())}"
        )
    except RazorpayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        client.close()

    order = response.body
    return {
        "order_id": order["id"],
        "amount": int(sku["amount"]),
        "currency": "INR",
        "key_id": settings.razorpay_key_id,
        "checkout_config": storefront_checkout_config(connection_factory)["config"],
        "request_id": response.request_id,
    }


@router.get("/storefront/checkout-config")
def storefront_checkout_config(connection_factory: ConnFactory) -> dict[str, Any]:
    """The active STEER_METHOD hint, as a Razorpay checkout display block.

    Shape from the Standard Checkout docs, "Configure Payment Methods": a display block with
    hide and sequence entries. See BUILD_LOG for the note isolating this assumption.
    """
    import json as _json

    conn = connection_factory()
    row = conn.execute(
        "SELECT h.hide_json, h.sequence_json, h.incident_id, i.segment_key, i.root_cause "
        "FROM checkout_hints h LEFT JOIN incidents i ON i.id = h.incident_id "
        "WHERE h.active_to IS NULL ORDER BY h.active_from DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return {"config": None, "hint": None}

    hide = _json.loads(row["hide_json"] or "[]")
    sequence = _json.loads(row["sequence_json"] or "[]")
    display: dict[str, Any] = {}
    if hide:
        display["hide"] = [{"method": method} for method in hide]
    if sequence:
        display["sequence"] = [f"block.{method}" for method in sequence]
        display["preferences"] = {"show_default_blocks": True}
    return {
        "config": {"display": display} if display else None,
        "hint": {
            "incident_id": row["incident_id"],
            "segment_key": row["segment_key"],
            "root_cause": row["root_cause"],
            "hidden": hide,
            "preferred": sequence,
        },
    }


@router.post("/storefront/simulate-failure", dependencies=[Depends(require_token)])
def storefront_simulate_failure(connection_factory: ConnFactory) -> dict[str, Any]:
    """Dev only. Post a synthetic payment.failed so the Overview reacts without a real failure."""
    settings = get_settings()
    if not settings.is_dev:
        raise HTTPException(status_code=404, detail="not found")

    now = int(time.time())
    conn = connection_factory()
    customer_id = "cust_storefront_demo"
    if repo.get_customer(conn, customer_id) is None:
        repo.insert_customer(
            conn,
            {
                "id": customer_id,
                "ref_hash": repo.ref_hash(customer_id),
                "consent": 1,
                "locale": "en",
                "preferred_method": "upi",
                "upi_handle": "okhdfcbank",
                "typical_amount": 129900,
                "created_at": now,
            },
        )
    order_id = f"order_demo_{now}"
    repo.upsert_order(
        conn,
        {
            "id": order_id,
            "customer_id": customer_id,
            "amount": 129900,
            "status": "attempted",
            "source": "sim",
            "created_at": now,
        },
    )
    repo.upsert_attempt(
        conn,
        {
            "id": f"pay_demo_{now}",
            "order_id": order_id,
            "customer_id": customer_id,
            "method": "upi",
            "upi_handle": "okhdfcbank",
            "nb_bank": "HDFC",
            "status": "failed",
            "error_code": "GATEWAY_ERROR",
            "error_source": "bank",
            "error_step": "payment_debit_request",
            "error_reason": "bank_technical_error",
            "error_description": "Payment failed due to a technical error at bank.",
            "created_at": now,
            "raw_json": "{}",
        },
    )
    BUS.publish("attempt", {"order_id": order_id, "status": "failed", "method": "upi"})
    return {"order_id": order_id, "created_at": now}
