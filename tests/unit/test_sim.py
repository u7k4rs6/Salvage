"""Simulator behaviour: Architecture section 9 and docs/01_PRD.md sections 10 and 12."""

from __future__ import annotations

import json

import pytest

from salvage import repo
from salvage.db import open_migrated
from salvage.sim import params as params_mod
from salvage.sim.clock import IstCalendar, SimClock
from salvage.sim.merchant import build_catalogue, build_customers
from salvage.sim.response import ResponseModel, p_organic_for_amount
from salvage.sim.rng import Streams, substream
from salvage.sim.runner import run_scenario
from salvage.sim.traffic import arrivals_per_minute


@pytest.fixture
def small(small_params_path):
    return params_mod.load(small_params_path)


# -- parameters ------------------------------------------------------------


def test_shipped_params_load_and_validate():
    params = params_mod.default_params()
    assert set(params.scenarios) >= {"S0", "S1", "S2", "S3", "S4"}
    assert params.scenario("S5").implemented is False


def test_every_error_value_in_params_is_published_by_razorpay():
    """A typo in a reason name would otherwise reach the results unchallenged."""
    params = params_mod.default_params()
    params_mod.validate(params.raw)  # raises on an unpublished reason, step or source


def test_bad_reason_in_params_is_refused(small_params_path):
    import yaml

    raw = yaml.safe_load(small_params_path.read_text())
    raw["organic"]["error_profiles"]["upi"][0]["reason"] = "not_a_razorpay_reason"
    with pytest.raises(params_mod.ParamsError, match="published Razorpay reason"):
        params_mod.validate(raw)


# -- clock -----------------------------------------------------------------


def test_sim_clock_never_runs_backwards():
    clock = SimClock(1000)
    clock.advance(60)
    assert clock.now() == 1060
    with pytest.raises(ValueError):
        clock.advance(-1)
    with pytest.raises(ValueError):
        clock.set(999)


def test_ist_calendar_hours_and_bands():
    params = params_mod.default_params()
    calendar = IstCalendar(params.ist_offset)
    # The epoch is IST midnight by construction.
    assert calendar.hour_of_day(params.epoch) == 0
    assert calendar.hour_of_day(params.epoch + 19 * 3600) == 19
    assert calendar.hour_band(params.epoch) == 0
    assert calendar.hour_band(params.epoch + 19 * 3600) == 3
    assert calendar.start_of_day(params.epoch + 5000) == params.epoch
    assert calendar.is_quiet_hours(params.epoch + 22 * 3600)
    assert not calendar.is_quiet_hours(params.epoch + 12 * 3600)


# -- random streams --------------------------------------------------------


def test_substreams_are_reproducible_and_independent():
    a = substream(7, "attempts").random(20)
    b = substream(7, "attempts").random(20)
    assert (a == b).all()

    used, fresh = Streams(7), Streams(7)
    used.customers.random(1000)  # a policy consuming another stream must not shift this one
    assert (used.attempts.random(5) == fresh.attempts.random(5)).all()


def test_different_seeds_give_different_worlds():
    assert not (substream(1, "attempts").random(20) == substream(2, "attempts").random(20)).all()


# -- merchant fixture ------------------------------------------------------


def test_customer_base_matches_the_configured_proportions(small):
    customers = build_customers(small, Streams(0))
    assert len(customers) == small.merchant["customer_count"]

    consent = sum(c.consent for c in customers) / len(customers)
    hi_en = sum(c.locale == "hi_en" for c in customers) / len(customers)
    alternate = sum(c.alternate is not None for c in customers) / len(customers)
    assert abs(consent - small.merchant["consent_rate"]) < 0.06
    assert abs(hi_en - small.merchant["locale_hi_en_rate"]) < 0.06
    assert abs(alternate - small.merchant["secondary_instrument_rate"]) < 0.06

    # An alternate is always a different method, or the steer in M2 would be meaningless.
    for customer in customers:
        if customer.alternate is not None:
            assert customer.alternate.method != customer.preferred.method


def test_catalogue_prices_stay_inside_the_configured_bounds(small):
    catalogue = build_catalogue(small, Streams(0))
    assert len(catalogue) == small.merchant["sku_count"]
    for sku in catalogue:
        assert small.merchant["sku_min_paise"] <= sku.amount <= small.merchant["sku_max_paise"]


def test_customer_rows_carry_no_contact_or_email(small):
    from salvage.sim.merchant import customer_rows

    rows = customer_rows(build_customers(small, Streams(0)), created_at=0)
    text = json.dumps(rows)
    assert "@" not in text
    assert "+91" not in text


# -- traffic ---------------------------------------------------------------


def test_arrivals_follow_the_diurnal_curve(small):
    day = small.epoch
    arrivals = arrivals_per_minute(small, day, Streams(0).arrivals)
    assert len(arrivals) == 1440
    peak = arrivals[19 * 60 : 23 * 60].sum()
    trough = arrivals[2 * 60 : 6 * 60].sum()
    assert peak > 4 * trough
    # Daily total is attempts_per_day in expectation, within Poisson noise.
    assert abs(int(arrivals.sum()) - small.traffic["attempts_per_day"]) < 400


# -- response model --------------------------------------------------------


def test_p_organic_value_bands(small):
    assert p_organic_for_amount(small, 40000) == 0.28
    assert p_organic_for_amount(small, 100000) == 0.34
    assert p_organic_for_amount(small, 200000) == 0.40
    assert p_organic_for_amount(small, 900000) == 0.46


def test_hard_decline_lowers_the_organic_retry_probability(small):
    model = ResponseModel(small, Streams(0).response)
    soft = model.draw(amount_paise=200000, failed_at=0, error_reason="insufficient_funds")
    hard = model.draw(amount_paise=200000, failed_at=0, error_reason="debit_instrument_blocked")
    assert hard.p_organic < soft.p_organic
    assert hard.p_organic == pytest.approx(
        soft.p_organic * small.response["p_organic_hard_decline_multiplier"]
    )


def test_organic_retry_is_within_twenty_four_hours(small):
    model = ResponseModel(small, Streams(3).response)
    for _ in range(500):
        outcome = model.draw(amount_paise=250000, failed_at=1000, error_reason="payment_failed")
        if outcome.will_retry:
            assert 1000 < outcome.retry_at <= 1000 + 86400


# -- full runs -------------------------------------------------------------


def _run(tmp_path, scenario, seed, params_path, name="run.db"):
    conn = open_migrated(tmp_path / name)
    try:
        return run_scenario(conn, scenario=scenario, seed=seed, params_path=params_path), conn
    except BaseException:
        conn.close()
        raise


def test_s1_run_writes_events_and_ground_truth(tmp_path, small_params_path, small):
    result, conn = _run(tmp_path, "S1", 1, small_params_path)
    try:
        assert result.attempts > 0
        assert result.failures > 0
        assert repo.count_attempts(conn) == result.attempts
        assert repo.count_orders(conn) == result.orders
        assert repo.count_truth_attempts(conn, result.run_id) == result.failures

        truth = repo.truth_incidents_for_run(conn, result.run_id)
        assert len(truth) == 1
        assert truth[0]["true_cause"] == "issuer_outage"
        assert truth[0]["end_ts"] - truth[0]["start_ts"] == 90 * 60

        # The fault segment fails far more than its siblings inside the window.
        start, end = truth[0]["start_ts"], truth[0]["end_ts"]
        rows = {
            row["upi_handle"]: row["fr"]
            for row in conn.execute(
                "SELECT upi_handle, 1.0 * SUM(status = 'failed') / COUNT(*) AS fr "
                "FROM payment_attempts WHERE method = 'upi' AND created_at >= ? "
                "AND created_at < ? GROUP BY 1",
                (start, end),
            )
        }
        assert rows["okhdfcbank"] > 0.80
        for handle, rate in rows.items():
            if handle != "okhdfcbank":
                assert rate < 0.35
    finally:
        conn.close()


def test_s0_has_no_fault_and_no_fault_caused_attempts(tmp_path, small_params_path):
    result, conn = _run(tmp_path, "S0", 0, small_params_path)
    try:
        assert repo.truth_incidents_for_run(conn, result.run_id) == []
        causes = {
            row["truth_cause"]
            for row in conn.execute("SELECT DISTINCT truth_cause FROM payment_attempts")
        }
        assert causes <= {"none", "organic"}
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("scenario", "cause"),
    [
        ("S1", "issuer_outage"),
        ("S2", "auth_failure_bin"),
        ("S3", "gateway_degradation"),
        ("S4", "merchant_config"),
    ],
)
def test_every_scenario_produces_its_own_truth_cause(tmp_path, small_params_path, scenario, cause):
    result, conn = _run(tmp_path, scenario, 2, small_params_path, name=f"{scenario}.db")
    try:
        counts = {
            row["truth_cause"]: row["n"]
            for row in conn.execute(
                "SELECT truth_cause, COUNT(*) AS n FROM payment_attempts GROUP BY 1"
            )
        }
        assert counts.get(cause, 0) > 0
        assert repo.truth_incidents_for_run(conn, result.run_id)[0]["true_cause"] == cause
    finally:
        conn.close()


def test_s5_is_refused_because_it_is_stretch(tmp_path, small_params_path):
    conn = open_migrated(tmp_path / "s5.db")
    try:
        with pytest.raises(params_mod.ParamsError, match="not implemented"):
            run_scenario(conn, scenario="S5", seed=0, params_path=small_params_path)
    finally:
        conn.close()


def test_same_seed_gives_an_identical_world(tmp_path, small_params_path):
    signatures = []
    for name in ("a.db", "b.db"):
        result, conn = _run(tmp_path, "S1", 4, small_params_path, name=name)
        try:
            rows = conn.execute(
                "SELECT id, customer_id, method, status, error_reason, created_at "
                "FROM payment_attempts ORDER BY id"
            ).fetchall()
            signatures.append([tuple(row) for row in rows])
        finally:
            conn.close()
    assert signatures[0] == signatures[1]
    assert len(signatures[0]) > 100


def test_different_seeds_give_different_runs(tmp_path, small_params_path):
    counts = []
    for seed, name in ((5, "s5.db"), (6, "s6.db")):
        result, conn = _run(tmp_path, "S1", seed, small_params_path, name=name)
        conn.close()
        counts.append((result.attempts, result.failures))
    assert counts[0] != counts[1]


def test_simulated_events_are_shaped_like_a_razorpay_payment_entity(tmp_path, small_params_path):
    result, conn = _run(tmp_path, "S2", 1, small_params_path)
    try:
        row = conn.execute(
            "SELECT raw_json FROM payment_attempts WHERE status = 'failed' AND method = 'card' "
            "LIMIT 1"
        ).fetchone()
        entity = json.loads(row["raw_json"])
        for field in (
            "id",
            "entity",
            "amount",
            "currency",
            "status",
            "order_id",
            "method",
            "error_code",
            "error_source",
            "error_step",
            "error_reason",
            "error_description",
            "created_at",
            "notes",
            "acquirer_data",
        ):
            assert field in entity, field
        assert entity["entity"] == "payment"
        assert set(entity["card"]) >= {"network", "issuer", "iin", "last4"}

        upi = conn.execute(
            "SELECT raw_json FROM payment_attempts WHERE method = 'upi' LIMIT 1"
        ).fetchone()
        upi_entity = json.loads(upi["raw_json"])
        assert "@" in upi_entity["vpa"]
        assert upi_entity["bank"]
    finally:
        conn.close()


def test_run_appends_exactly_two_ledger_entries_and_the_chain_verifies(tmp_path, small_params_path):
    from salvage.ledger import verify

    result, conn = _run(tmp_path, "S1", 1, small_params_path)
    try:
        kinds = [row["kind"] for row in conn.execute("SELECT kind FROM ledger ORDER BY seq")]
        assert kinds == ["sim.run.started", "sim.run.finished"]
        assert verify(conn).ok
    finally:
        conn.close()
