"""The ledger commits to the event stream, not only to the counts.

Carry-over item 3 from the M1 review. The hash chain proves a ledger entry has not been edited.
The stream digest inside sim.run.finished proves the events that entry describes have not been
edited either. Both are needed: neither catches what the other catches.
"""

from __future__ import annotations

import pytest

from salvage.db import open_migrated
from salvage.ledger import verify
from salvage.sim.runner import run_scenario, stream_digest
from salvage.sim.verify import StreamNotCommitted, verify_stream


@pytest.fixture
def run(tmp_path, small_params_path):
    conn = open_migrated(tmp_path / "stream.db")
    result = run_scenario(conn, scenario="S1", seed=2, params_path=small_params_path)
    yield result, conn
    conn.close()


def test_a_fresh_run_verifies(run):
    result, conn = run
    outcome = verify_stream(conn, result.run_id)
    assert outcome.ok
    assert outcome.computed_attempts == result.attempts
    assert outcome.committed_digest == result.stream_digest
    assert "Stream intact" in str(outcome)


def test_verify_defaults_to_the_latest_run(run):
    result, conn = run
    assert verify_stream(conn).run_id == result.run_id


def test_changing_one_attempt_field_breaks_the_stream_but_not_the_chain(run):
    result, conn = run
    conn.execute(
        "UPDATE payment_attempts SET status = 'captured' WHERE id = "
        "(SELECT id FROM payment_attempts WHERE status = 'failed' ORDER BY created_at LIMIT 1)"
    )
    outcome = verify_stream(conn, result.run_id)
    assert not outcome.ok
    assert "at least one row differs" in outcome.detail
    # The hash chain is still intact, which is exactly why the commitment is needed.
    assert verify(conn).ok


def test_deleting_an_attempt_breaks_the_stream(run):
    result, conn = run
    conn.execute(
        "DELETE FROM payment_attempts WHERE id = "
        "(SELECT id FROM payment_attempts ORDER BY created_at DESC LIMIT 1)"
    )
    outcome = verify_stream(conn, result.run_id)
    assert not outcome.ok
    assert "attempt count changed" in outcome.detail


def test_inserting_an_extra_attempt_breaks_the_stream(run):
    result, conn = run
    template = conn.execute("SELECT * FROM payment_attempts LIMIT 1").fetchone()
    columns = list(template.keys())
    values = {column: template[column] for column in columns}
    values["id"] = "pay_forged000000001"
    placeholders = ", ".join(f":{c}" for c in columns)
    conn.execute(
        f"INSERT INTO payment_attempts ({', '.join(columns)}) VALUES ({placeholders})", values
    )
    outcome = verify_stream(conn, result.run_id)
    assert not outcome.ok


def test_changing_an_error_code_breaks_the_stream(run):
    """error_code is one of the committed fields, so rewriting a diagnosis input is caught."""
    result, conn = run
    conn.execute(
        "UPDATE payment_attempts SET error_code = 'SERVER_ERROR' WHERE id = "
        "(SELECT id FROM payment_attempts WHERE status = 'failed' ORDER BY created_at LIMIT 1)"
    )
    assert not verify_stream(conn, result.run_id).ok


def test_changing_something_outside_the_committed_fields_does_not_break_it(run):
    """The commitment covers the fields it says it covers, and no more.

    error_description is deliberately not committed: it is a free-text string Razorpay may reword,
    and committing to it would make the digest fragile without adding anything the detector or the
    policy engine reads.
    """
    result, conn = run
    conn.execute("UPDATE payment_attempts SET error_description = 'reworded'")
    assert verify_stream(conn, result.run_id).ok


def test_an_unknown_run_id_is_reported_clearly(run):
    _, conn = run
    with pytest.raises(StreamNotCommitted, match="no simulator run"):
        verify_stream(conn, "run_that_does_not_exist")


def test_an_empty_database_says_so(tmp_path):
    conn = open_migrated(tmp_path / "empty.db")
    try:
        with pytest.raises(StreamNotCommitted, match="no simulator runs"):
            verify_stream(conn)
    finally:
        conn.close()


def test_the_digest_is_stable_across_recomputation(run):
    result, conn = run
    first, count_a = stream_digest(conn, sim_start=result.sim_start, sim_end=result.sim_end)
    second, count_b = stream_digest(conn, sim_start=result.sim_start, sim_end=result.sim_end)
    assert first == second == result.stream_digest
    assert count_a == count_b == result.attempts
