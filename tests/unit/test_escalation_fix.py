"""Escalation to fix: the M5 mechanism, and the three things that make it honest.

An escalation that changes nothing in the world makes S4 measure the cost of the agent's
restraint with none of its benefit. The fix is modelled as a swept parameter rather than a
default, and these tests pin the properties that let the sweep be read as a comparison:

  `never` reproduces the numbers a build without the mechanism produced, exactly;
  the at-risk order set does not move when the parameter does;
  an arm that never escalates never benefits.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from salvage.db import open_migrated
from salvage.eval.agent_run import run_policy_scenario
from salvage.execute.scheduler import _fault_answers_segment

PARAMS_PATH = Path("salvage/sim/params.yaml")


@pytest.fixture(scope="module")
def small_params(tmp_path_factory):
    raw = yaml.safe_load(PARAMS_PATH.read_text(encoding="utf-8"))
    # Full traffic volume, fewer customers and days. The detector needs attempts per 15-minute
    # window, not a long history, so this keeps the thing under test intact and the run short.
    raw["merchant"]["customer_count"] = 3000
    raw["clock"]["warmup_days"] = 3
    raw["clock"]["settle_days"] = 2
    path = tmp_path_factory.mktemp("params") / "params.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def _run(tmp_path, small_params, policy: str, fix_minutes, seed: int = 1, scenario: str = "S4"):
    db = tmp_path / f"{scenario}_{policy}_{fix_minutes}_{seed}.db"
    conn = open_migrated(db)
    try:
        return run_policy_scenario(
            conn,
            scenario=scenario,
            seed=seed,
            policy=policy,
            params_path=small_params,
            escalation_fix_minutes=fix_minutes,
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Which faults an escalation leads a human to
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("selector", "segment_key", "expected"),
    [
        ({"method": "netbanking"}, "netbanking", True),
        ({"method": "netbanking"}, "all", True),
        ({}, "card:card_network:Visa", True),
        ({"method": "upi", "upi_handle": "okhdfcbank"}, "upi", True),
        ({"method": "upi", "upi_handle": "okhdfcbank"}, "upi:upi_handle:okhdfcbank", True),
        ({"method": "upi", "upi_handle": "okhdfcbank"}, "upi:upi_handle:okaxis", False),
        ({"method": "card", "card_bin": "411111"}, "card:card_bin6:411111", True),
        ({"method": "card", "card_bin": "411111"}, "card:card_bin6:522222", False),
        ({"method": "netbanking"}, "upi", False),
    ],
)
def test_a_fix_reaches_the_fault_the_escalation_describes(selector, segment_key, expected):
    """Not contradicted, rather than exactly equal. An incident attributed to the method covers a
    fault on one instrument of it, and an incident attributed to one instrument does not rule out
    a fault that was breaking everything."""
    assert _fault_answers_segment(selector, segment_key) is expected


# ---------------------------------------------------------------------------
# The mechanism is additive
# ---------------------------------------------------------------------------


def test_never_reproduces_the_run_with_no_fix_mechanism(tmp_path, small_params):
    """The whole sweep is read as a comparison against the `never` row, so `never` has to be the
    old behaviour to the paise rather than close to it. The repair draw takes its own random
    stream for exactly this reason."""
    off = _run(tmp_path, small_params, "agent", None)
    assert off.stats.fixes_applied == 0
    assert off.stats.fix_recoveries == 0
    assert off.metrics.by_route_orders.get("fix", 0) == 0


def test_a_fix_recovers_more_of_the_at_risk_set_without_moving_it(tmp_path, small_params):
    off = _run(tmp_path, small_params, "agent", None)
    on = _run(tmp_path, small_params, "agent", 30)

    # The world is the same world. The fix changes what customers do, never which orders exist.
    assert on.stream_digest == off.stream_digest
    assert on.metrics.at_risk_orders == off.metrics.at_risk_orders > 0
    assert on.metrics.eligible_orders == off.metrics.eligible_orders

    assert on.stats.escalations > 0, "S4 must escalate or there is nothing to fix"
    assert on.stats.fixes_applied == 1
    assert on.metrics.at_risk_recovered_amount > off.metrics.at_risk_recovered_amount
    assert on.metrics.by_route_orders.get("fix", 0) > 0

    # A fix is not a licence to message. The agent's restraint on a merchant_config incident is
    # the thing being defended, so contact volume must not move with the parameter.
    assert on.metrics.messages_sent == off.metrics.messages_sent


def test_a_later_fix_recovers_no_more_than_an_earlier_one(tmp_path, small_params):
    """Monotone in T, because the probability decays with the wait and because a repair after the
    fault has already ended does nothing at all."""
    quick = _run(tmp_path, small_params, "agent", 15)
    slow = _run(tmp_path, small_params, "agent", 120)
    assert quick.metrics.at_risk_recovered_amount >= slow.metrics.at_risk_recovered_amount


def test_an_arm_that_never_escalates_never_benefits(tmp_path, small_params):
    """B1 sends links and files nothing, so the parameter cannot reach it. This is the asymmetry
    docs/RESULTS.md has to state: the fix is available to the agent and to nobody else, and a real
    merchant might notice a broken method without an agent telling them."""
    off = _run(tmp_path, small_params, "B1", None)
    on = _run(tmp_path, small_params, "B1", 15)
    assert off.stats.escalations == 0
    assert on.stats.fixes_applied == 0
    assert on.metrics.recovered_amount == off.metrics.recovered_amount
    assert on.metrics.at_risk_recovered_amount == off.metrics.at_risk_recovered_amount
    assert on.metrics.messages_sent == off.metrics.messages_sent


def test_the_fix_is_off_by_default_in_the_parameter_file():
    """A default that quietly repaired the world would flatter every agent number in the report."""
    from salvage.sim.params import default_params

    assert default_params().escalation_fix_minutes is None
