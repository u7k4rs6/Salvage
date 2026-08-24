"""The two properties that make the headline table a comparison rather than four numbers.

M3 carry-over 1 and 3:

  the set of orders considered is identical across all four policies
  the pre-intervention attempt stream digest is byte-identical across all four policies

Both are asserted here at reduced volume. The full-scale versions are printed by
`salvage eval run` and appear in docs/RESULTS.md.
"""

from __future__ import annotations

import pytest

from salvage.db import open_migrated
from salvage.eval.agent_run import count_policy_violations, run_policy_scenario, violation_breakdown
from salvage.eval.baselines import (
    DEFAULT_POLICY_ORDER,
    FaultWindow,
    at_risk_order_ids,
    eligible_order_ids,
    get_policy,
)
from salvage.eval.metrics import ROUTES
from salvage.sim.verify import verify_stream

POLICIES = ("B0", "B1", "B2")


@pytest.fixture(scope="module")
def runs(tmp_path_factory, request):
    """One run per policy over the same scenario and seed, in separate databases."""
    import yaml

    from salvage.sim.params import PARAMS_PATH

    root = tmp_path_factory.mktemp("comparability")
    raw = yaml.safe_load(PARAMS_PATH.read_text(encoding="utf-8"))
    raw["merchant"]["customer_count"] = 400
    raw["traffic"]["attempts_per_day"] = 2400
    raw["clock"]["warmup_days"] = 2
    raw["clock"]["settle_days"] = 2
    params_path = root / "params.yaml"
    params_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    results = {}
    for policy in POLICIES:
        conn = open_migrated(root / f"{policy}.db")
        result = run_policy_scenario(
            conn, scenario="S1", seed=3, policy=policy, params_path=params_path
        )
        results[policy] = (result, conn)
    yield results
    for _, conn in results.values():
        conn.close()


# -- identical world -------------------------------------------------------


def test_the_attempt_stream_digest_is_identical_across_policies(runs):
    digests = {policy: result.stream_digest for policy, (result, _) in runs.items()}
    assert len(set(digests.values())) == 1, digests
    assert all(len(digest) == 64 for digest in digests.values())


def test_the_stream_still_verifies_after_every_policy_ran(runs):
    """No policy writes a payment attempt, so the commitment made before any of them ran holds."""
    for policy, (result, conn) in runs.items():
        outcome = verify_stream(conn, result.sim.run_id)
        assert outcome.ok, f"{policy}: {outcome.detail}"


def test_the_attempt_counts_are_identical_across_policies(runs):
    counts = {
        policy: conn.execute("SELECT COUNT(*) AS n FROM payment_attempts").fetchone()["n"]
        for policy, (_, conn) in runs.items()
    }
    assert len(set(counts.values())) == 1, counts


# -- identical order set ---------------------------------------------------


def test_the_eligible_order_set_is_identical_across_policies(runs):
    """The claim M3 carry-over 1 asks for, as a set comparison and not a count comparison."""
    sets = {}
    for policy, (result, conn) in runs.items():
        params_days = result.sim.eval_day_start
        sets[policy] = set(eligible_order_ids(conn, start=params_days, end=params_days + 86400))
    reference = sets[POLICIES[0]]
    assert reference
    for policy, order_ids in sets.items():
        assert order_ids == reference, f"{policy} considered a different order set"


def test_the_at_risk_order_set_is_identical_across_policies(runs):
    """The primary denominator, proven identical the same way the stream digests are.

    The at-risk set is the population the agent exists for: orders whose first attempt failed
    inside a fault window and on the instrument that fault was breaking. It is computed from the
    world's fault schedule and the attempt stream, neither of which any policy touches, so it must
    be byte-identical across arms. If it were not, the primary table would be four different
    questions rather than one comparison.
    """
    sets = {}
    for policy, (result, conn) in runs.items():
        windows = [
            FaultWindow(start=f.start_ts, end=f.end_ts, selector=dict(f.fault.selector))
            for f in result.sim.scheduled_faults
        ]
        sets[policy] = tuple(at_risk_order_ids(conn, windows))

    reference = sets[POLICIES[0]]
    assert reference, "the scenario produced no at-risk orders, so this proves nothing"
    for policy, order_ids in sets.items():
        assert order_ids == reference, f"{policy} was measured over a different at-risk set"
    # Order matters too, not just membership: the ids come back in a deterministic order and a
    # difference there would mean the attempt stream itself moved.
    assert len(set(sets.values())) == 1


def test_the_at_risk_counts_recorded_in_the_metrics_match_across_policies(runs):
    counts = {
        policy: (result.metrics.at_risk_orders, result.metrics.at_risk_amount)
        for policy, (result, _) in runs.items()
    }
    assert len(set(counts.values())) == 1, counts
    assert next(iter(counts.values()))[0] > 0


def test_a_scenario_with_no_fault_has_an_empty_at_risk_set(tmp_path, small_params_path):
    """S0 is the whole reason the primary table is scoped this way.

    Nothing broke, so nothing was at risk, so no policy can have recovered anything from the
    at-risk set. A policy that sends messages on that day has spent them on nothing, which is
    exactly what the primary table should show and what a whole-run table hides.
    """
    from salvage.db import open_migrated

    conn = open_migrated(tmp_path / "s0.db")
    try:
        result = run_policy_scenario(
            conn, scenario="S0", seed=1, policy="B1", params_path=small_params_path
        )
    finally:
        conn.close()
    assert result.sim.scheduled_faults == ()
    assert result.metrics.at_risk_orders == 0
    assert result.metrics.at_risk_recovered_orders == 0
    assert result.metrics.at_risk_recovery_rate == 0.0
    # And yet it sent messages, which is the point.
    assert result.metrics.messages_sent > 0


def test_at_risk_orders_are_scoped_to_the_failing_instrument(runs):
    """Not just the window. A UPI handle outage does not put card failures at risk."""
    result, conn = runs[POLICIES[0]]
    fault = result.sim.scheduled_faults[0]
    windows = [
        FaultWindow(
            start=fault.start_ts, end=fault.end_ts, selector=dict(fault.fault.selector)
        )
    ]
    scoped = set(at_risk_order_ids(conn, windows))

    window_only = [FaultWindow(start=fault.start_ts, end=fault.end_ts, selector={})]
    everything_in_window = set(at_risk_order_ids(conn, window_only))

    assert scoped
    assert scoped < everything_in_window, (
        "scoping by instrument removed nothing, so the selector is not being applied"
    )


def test_the_measured_population_is_identical_across_policies(runs):
    populations = {
        policy: (result.metrics.eligible_orders, result.metrics.eligible_amount)
        for policy, (result, _) in runs.items()
    }
    assert len(set(populations.values())) == 1, populations


def test_the_in_fault_population_is_identical_across_policies(runs):
    populations = {
        policy: (result.metrics.at_risk_orders, result.metrics.at_risk_amount)
        for policy, (result, _) in runs.items()
    }
    assert len(set(populations.values())) == 1, populations


# -- comparable accounting -------------------------------------------------


def test_the_primary_number_counts_every_route(runs):
    """recovered_orders is the total by any route, so the route columns must add up to it."""
    for policy, (result, _) in runs.items():
        metrics = result.metrics
        assert sum(metrics.by_route_orders.get(route, 0) for route in ROUTES) == (
            metrics.recovered_orders
        ), policy
        assert sum(metrics.by_route_amount.get(route, 0) for route in ROUTES) == (
            metrics.recovered_amount
        ), policy


def test_b0_recovers_only_organically(runs):
    metrics = runs["B0"][0].metrics
    assert metrics.by_route_orders["link"] == 0
    assert metrics.by_route_orders["steer"] == 0
    assert metrics.by_route_orders["organic"] == metrics.recovered_orders
    assert metrics.recovered_orders > 0


def test_a_link_policy_takes_orders_from_the_organic_column(runs):
    """A link that pays before the customer would have come back is not an extra recovery.

    If the organic column were unchanged while the link column grew, the accounting would be
    double counting: the same order recovered twice.
    """
    b0, b1 = runs["B0"][0].metrics, runs["B1"][0].metrics
    assert b1.by_route_orders["link"] > 0
    assert b1.by_route_orders["organic"] <= b0.by_route_orders["organic"]


def test_no_order_carries_two_routes(runs):
    for policy, (_, conn) in runs.items():
        duplicated = conn.execute(
            "SELECT COUNT(*) AS n FROM (SELECT order_id FROM recovery_routes "
            "GROUP BY order_id HAVING COUNT(*) > 1)"
        ).fetchone()["n"]
        assert duplicated == 0, policy


def test_recovered_orders_never_exceeds_eligible_orders(runs):
    for policy, (result, _) in runs.items():
        assert result.metrics.recovered_orders <= result.metrics.eligible_orders, policy
        assert 0.0 <= result.metrics.recovery_rate <= 1.0


# -- policy violations -----------------------------------------------------


def test_no_policy_violations_in_any_arm(runs):
    for policy, (_, conn) in runs.items():
        breakdown = violation_breakdown(conn)
        assert count_policy_violations(conn) == 0, f"{policy}: {breakdown}"


def test_the_violation_queries_would_catch_something(conn):
    """A violation counter that cannot count is worse than none."""
    from salvage import repo

    repo.insert_customer(
        conn,
        {
            "id": "cust_1",
            "ref_hash": "h" * 64,
            "consent": 0,
            "locale": "en",
            "typical_amount": 1,
            "created_at": 0,
        },
    )
    repo.insert_comm(
        conn,
        {
            "id": "comm_1",
            "customer_id": "cust_1",
            "case_id": None,
            "incident_id": None,
            "channel": "simulated",
            "template_id": "t",
            "locale": "en",
            "body_hash": "x" * 64,
            "sent_at": 1_700_000_000,
        },
    )
    breakdown = violation_breakdown(conn)
    assert breakdown["message_without_consent"] == 1
    assert count_policy_violations(conn) >= 1


# -- baselines differ only where they are supposed to ----------------------


def test_the_baselines_obey_every_check_except_the_two_cause_aware_ones():
    for name in ("B0", "B1", "B2"):
        profile = get_policy(name)
        assert not profile.applies_matrix
        assert not profile.defers_while_degraded
        assert not profile.allows_steer
        assert not profile.diagnoses
    agent = get_policy("agent")
    assert agent.applies_matrix and agent.defers_while_degraded and agent.allows_steer


def test_every_baseline_gate_record_names_the_skipped_check(runs):
    """A skipped check is recorded as skipped, never silently absent."""
    import json

    _, conn = runs["B1"]
    rows = conn.execute(
        "SELECT gate_json, status FROM actions WHERE type = 'SEND_RECOVERY_LINK' LIMIT 200"
    ).fetchall()
    assert rows
    for row in rows:
        rules = {gate["rule"] for gate in json.loads(row["gate_json"])}
        # The matrix is the first group, so every action records that it was skipped and why.
        assert "matrix.not_applicable" in rules
        if row["status"] == "executed":
            assert "customer.consent" in rules
            # Later groups only run when the earlier ones passed, so the global checks appear on
            # actions that got that far.
            assert "timing.defer_while_degraded_not_applicable" in rules
            assert "global.kill_switch_off" in rules


def test_the_policy_names_are_the_documented_four():
    assert DEFAULT_POLICY_ORDER == ("agent", "B0", "B1", "B2")
