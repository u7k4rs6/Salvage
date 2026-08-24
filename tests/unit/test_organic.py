"""Organic retries and baseline B0.

Carry-over item 1 from the M1 review: without organic retries every order had exactly one attempt,
nobody ever came back, and B0 recovered nothing, which would have made every comparison in
docs/RESULTS.md meaningless.
"""

from __future__ import annotations

import pytest

from salvage.db import open_migrated
from salvage.eval.agent_run import run_policy_scenario
from salvage.eval.metrics import format_metrics_table
from salvage.sim.runner import run_scenario


@pytest.fixture
def s1_run(tmp_path, small_params_path):
    conn = open_migrated(tmp_path / "organic.db")
    result = run_scenario(conn, scenario="S1", seed=1, params_path=small_params_path)
    yield result, conn
    conn.close()


def test_attempts_exceed_orders(s1_run):
    result, conn = s1_run
    assert result.retries > 0
    assert result.attempts > result.orders
    assert result.attempts == result.first_attempts + result.retries
    assert result.first_attempts == result.orders

    counted = conn.execute("SELECT COUNT(*) AS n FROM payment_attempts").fetchone()["n"]
    orders = conn.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"]
    assert counted == result.attempts
    assert orders == result.orders
    assert counted > orders


def test_some_orders_have_more_than_one_attempt(s1_run):
    _, conn = s1_run
    multi = conn.execute(
        "SELECT COUNT(*) AS n FROM (SELECT order_id FROM payment_attempts "
        "GROUP BY order_id HAVING COUNT(*) > 1)"
    ).fetchone()["n"]
    assert multi > 0


def test_some_orders_reach_paid_with_no_intervention(s1_run):
    """The test the M1 review asked for: on S1 with no policy at all, customers come back."""
    result, conn = s1_run
    assert result.orders_paid_on_retry > 0

    recovered = conn.execute(
        """
        WITH first_attempt AS (
            SELECT order_id, status,
                   ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY created_at, id) AS rn
            FROM payment_attempts
        )
        SELECT COUNT(*) AS n FROM first_attempt f JOIN orders o ON o.id = f.order_id
        WHERE f.rn = 1 AND f.status = 'failed' AND o.status = 'paid'
        """
    ).fetchone()["n"]
    assert recovered > 0
    assert recovered == result.orders_paid_on_retry


def test_a_retry_uses_the_same_order_customer_and_instrument(s1_run):
    _, conn = s1_run
    row = conn.execute(
        "SELECT order_id FROM payment_attempts GROUP BY order_id HAVING COUNT(*) > 1 LIMIT 1"
    ).fetchone()
    attempts = conn.execute(
        "SELECT customer_id, method, upi_handle, card_bin, nb_bank FROM payment_attempts "
        "WHERE order_id = ? ORDER BY created_at",
        (row["order_id"],),
    ).fetchall()
    assert len(attempts) > 1
    first = tuple(attempts[0])
    for later in attempts[1:]:
        assert tuple(later) == first


def test_no_retry_lands_after_the_order_was_paid(s1_run):
    """A customer who has already paid does not come back to pay again."""
    _, conn = s1_run
    stragglers = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM payment_attempts a
        JOIN orders o ON o.id = a.order_id
        WHERE o.paid_at IS NOT NULL AND a.created_at > o.paid_at
        """
    ).fetchone()["n"]
    assert stragglers == 0


def test_the_settlement_tail_is_long_enough(s1_run):
    result, _ = s1_run
    assert result.dropped_retries == 0


def test_organic_recovery_is_measurable_and_non_zero(tmp_path, small_params_path):
    """B0's recovery is the floor every other policy is compared against."""
    conn = open_migrated(tmp_path / "b0.db")
    try:
        result = run_policy_scenario(
            conn, scenario="S1", seed=1, policy="B0", params_path=small_params_path
        )
    finally:
        conn.close()
    metrics = result.metrics
    assert metrics.eligible_orders > 0
    assert metrics.recovered_orders > 0
    assert 0.0 < metrics.recovery_rate < 1.0
    assert metrics.recovered_amount > 0
    assert metrics.at_risk_orders > 0
    # B0 does nothing, so every recovery it has is organic by definition.
    assert metrics.by_route_orders["organic"] == metrics.recovered_orders
    assert metrics.messages_sent == 0


def test_the_metrics_table_renders(tmp_path, small_params_path):
    conn = open_migrated(tmp_path / "b0t.db")
    try:
        result = run_policy_scenario(
            conn, scenario="S1", seed=1, policy="B0", params_path=small_params_path
        )
    finally:
        conn.close()
    table = format_metrics_table([result.metrics], title="Organic-only recovery (policy B0)")
    assert "scenario" in table
    assert "S1" in table
    assert "organic" in table


def test_two_runs_of_the_same_seed_produce_identical_retries(tmp_path, small_params_path):
    signatures = []
    for name in ("a.db", "b.db"):
        conn = open_migrated(tmp_path / name)
        try:
            run_scenario(conn, scenario="S1", seed=4, params_path=small_params_path)
            signatures.append(
                [
                    tuple(row)
                    for row in conn.execute(
                        "SELECT id, order_id, status, created_at FROM payment_attempts "
                        "ORDER BY created_at, id"
                    )
                ]
            )
        finally:
            conn.close()
    assert signatures[0] == signatures[1]
