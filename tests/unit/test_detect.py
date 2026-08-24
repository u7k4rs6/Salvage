"""Detector unit tests: Architecture section 5."""

from __future__ import annotations

import pytest

from salvage.detect import incidents as incidents_mod
from salvage.detect.monitor import (
    Baselines,
    WindowCounters,
    WindowStat,
    alpha_for,
    binomial_p_value,
    build_baselines,
    evaluate_window,
)
from salvage.detect.segments import ALL_KEY, keys_for_attempt, parent_key, parse_key
from salvage.detect.thresholds import FROZEN, Thresholds
from salvage.sim.clock import IstCalendar

CAL = IstCalendar()


# -- segment keys ----------------------------------------------------------


def test_upi_attempt_produces_method_handle_and_bank_keys():
    denominators, numerators = keys_for_attempt(
        {
            "method": "upi",
            "upi_handle": "okhdfcbank",
            "nb_bank": "HDFC",
            "status": "failed",
            "error_step": "payment_debit_request",
        }
    )
    assert ALL_KEY in denominators
    assert "upi" in denominators
    assert "upi:upi_handle:okhdfcbank" in denominators
    assert "upi:nb_bank:HDFC" in denominators
    # The step key is a numerator only. Its denominator is every attempt of the method.
    assert "upi:error_step:payment_debit_request" not in denominators
    assert "upi:error_step:payment_debit_request" in numerators


def test_a_successful_attempt_has_no_numerator_keys():
    denominators, numerators = keys_for_attempt(
        {"method": "card", "card_bin": "411111", "status": "captured"}
    )
    assert denominators
    assert numerators == []


def test_card_attempt_produces_bin_issuer_and_network_keys():
    denominators, _ = keys_for_attempt(
        {
            "method": "card",
            "card_bin": "411111",
            "card_issuer": "HDFC",
            "card_network": "Visa",
            "status": "failed",
        }
    )
    assert {"card:card_bin6:411111", "card:card_issuer:HDFC", "card:card_network:Visa"} <= set(
        denominators
    )


def test_key_parsing_and_parents():
    assert parse_key("upi") == ("upi", None, None)
    assert parse_key("upi:upi_handle:okhdfcbank") == ("upi", "upi_handle", "okhdfcbank")
    assert parent_key("upi:upi_handle:okhdfcbank") == "upi"
    assert parent_key("upi") == ALL_KEY
    assert parent_key(ALL_KEY) is None


# -- baseline ladder -------------------------------------------------------


def _baselines(**kwargs) -> Baselines:
    return Baselines(thresholds=FROZEN, **kwargs)


def test_band_baseline_is_used_when_the_band_has_enough_attempts():
    baselines = _baselines(by_band={("upi", 3): (500, 50)}, by_key={"upi": (5000, 1000)})
    result = baselines.rate_for("upi", 3)
    assert result.source == "band"
    assert result.rate == pytest.approx(0.10)


def test_falls_back_to_the_key_rate_when_the_band_is_thin():
    baselines = _baselines(by_band={("upi", 3): (50, 5)}, by_key={"upi": (5000, 1000)})
    result = baselines.rate_for("upi", 3)
    assert result.source == "key"
    assert result.rate == pytest.approx(0.20)


def test_falls_back_to_the_method_rate_when_the_key_is_thin():
    baselines = _baselines(
        by_band={("upi:upi_handle:x", 3): (10, 1)},
        by_key={"upi:upi_handle:x": (30, 3)},
        by_method={"upi": (9000, 900)},
    )
    result = baselines.rate_for("upi:upi_handle:x", 3)
    assert result.source == "method"
    assert result.rate == pytest.approx(0.10)


def test_baseline_is_floored_so_a_spotless_week_cannot_be_zero():
    baselines = _baselines(by_band={("upi", 3): (5000, 0)})
    result = baselines.rate_for("upi", 3)
    assert result.source == "floor"
    assert result.rate == FROZEN.min_baseline_rate


def test_baseline_built_from_the_database_uses_the_trailing_window(conn):
    _seed_attempts(conn, start=1_000_000, count=600, method="upi", fail_every=4)
    baselines = build_baselines(conn, baseline_end=1_000_000 + 600 * 60)
    rate = baselines.rate_for("upi", CAL.hour_band(CAL.hour_of_day(1_000_000)))
    assert 0.2 < rate.rate < 0.3


# -- the statistical test --------------------------------------------------


def test_binomial_p_value_is_one_when_there_is_no_excess():
    assert binomial_p_value(1, 100, 0.10) == 1.0
    assert binomial_p_value(0, 0, 0.10) == 1.0


def test_binomial_p_value_shrinks_as_the_excess_grows():
    mild = binomial_p_value(20, 100, 0.10)
    strong = binomial_p_value(60, 100, 0.10)
    assert strong < mild < 1.0


def test_bonferroni_divides_by_live_keys_and_is_floored():
    assert alpha_for(1) == FROZEN.alpha
    assert alpha_for(5) == pytest.approx(FROZEN.alpha / 5)
    assert alpha_for(1000) == FROZEN.alpha_floor


def _counters(rows: list[tuple[int, list[str], list[str]]], start: int, end: int) -> WindowCounters:
    counters = WindowCounters(start, end, FROZEN.step_seconds)
    for ts, denominators, numerators in rows:
        counters.add(ts, denominators, numerators)
    counters.finalise()
    return counters


def test_each_condition_blocks_on_its_own():
    start, end = 0, 1800
    baselines = _baselines(by_band={("upi", 0): (10000, 1000)})  # baseline 0.10
    band = CAL.hour_band(CAL.hour_of_day(900 - 1))
    baselines.by_band = {("upi", band): (10000, 1000)}

    # Condition 1: too few attempts, even though every one of them failed.
    rows = [(t, ["upi"], ["upi"]) for t in range(0, 10 * 60, 60)]
    _, passing = _evaluate(_counters(rows, start, end), baselines)
    assert passing == []

    # Condition 2: plenty of attempts but the excess is under 0.15.
    rows = []
    for minute in range(15):
        for i in range(6):
            failed = i < 1  # about 0.167, only 0.067 above the 0.10 baseline
            rows.append((minute * 60 + i, ["upi"], ["upi"] if failed else []))
    _, passing = _evaluate(_counters(rows, start, end), baselines)
    assert passing == []

    # All conditions satisfied.
    rows = []
    for minute in range(15):
        for i in range(6):
            failed = i < 3  # 0.50 against a 0.10 baseline
            rows.append((minute * 60 + i, ["upi"], ["upi"] if failed else []))
    live, passing = _evaluate(_counters(rows, start, end), baselines)
    assert [stat.segment_key for stat in passing] == ["upi"]
    assert live[0].attempts == 90
    assert live[0].p_value < FROZEN.alpha


def _evaluate(counters: WindowCounters, baselines: Baselines):
    return evaluate_window(
        counters, baselines, window_start=0, window_end=900, calendar=CAL, thresholds=FROZEN
    )


# -- attribution -----------------------------------------------------------


def _stat(key: str, attempts: int, failures: int, baseline: float = 0.10) -> WindowStat:
    return WindowStat(
        segment_key=key,
        window_start=0,
        window_end=900,
        attempts=attempts,
        failures=failures,
        baseline_rate=baseline,
        baseline_source="band",
        p_value=1e-9,
    )


def test_one_bad_child_attributes_to_the_child_not_the_method():
    """S1: one UPI handle fails, the others are healthy."""
    passing = [
        _stat("upi", 200, 60),
        _stat("upi:upi_handle:okhdfcbank", 52, 48),
    ]
    groups = incidents_mod.attribute(passing)
    assert len(groups) == 1
    assert groups[0].attributed == "upi:upi_handle:okhdfcbank"


def test_a_broad_fault_stays_at_the_root_and_makes_one_incident():
    """S3: every method degrades, so no single child dominates."""
    passing = [
        _stat(ALL_KEY, 400, 180),
        _stat("upi", 240, 108),
        _stat("card", 100, 45),
        _stat("netbanking", 40, 18),
    ]
    groups = incidents_mod.attribute(passing)
    assert len(groups) == 1
    assert groups[0].attributed == ALL_KEY
    assert groups[0].breadth >= 2


def test_the_merchant_wide_key_needs_corroboration():
    """A merchant-wide key firing alone in the overnight trough opens nothing."""
    groups = incidents_mod.attribute([_stat(ALL_KEY, 22, 9, baseline=0.125)])
    assert groups == []


def test_a_step_key_alone_never_opens_an_incident():
    groups = incidents_mod.attribute([_stat("card:error_step:payment_authentication", 60, 24)])
    assert groups == []


def test_a_synthetic_parent_picks_the_narrowest_explaining_key():
    """The method key has not crossed yet, so three coincident child keys are all firing."""
    passing = [
        _stat("card:card_bin6:411111", 21, 12),
        _stat("card:card_issuer:HDFC", 21, 12),
        _stat("card:card_network:Visa", 36, 15),
    ]
    groups = incidents_mod.attribute(passing)
    assert len(groups) == 1
    assert groups[0].attributed == "card:card_bin6:411111"


def test_two_independent_faults_make_two_groups():
    passing = [
        _stat("upi", 200, 90),
        _stat("netbanking", 60, 40),
    ]
    groups = incidents_mod.attribute(passing)
    assert {group.attributed for group in groups} == {"upi", "netbanking"}


def test_family_and_ancestry():
    assert incidents_mod.same_family("upi", "upi:upi_handle:x")
    assert incidents_mod.same_family(ALL_KEY, "card")
    assert not incidents_mod.same_family("upi", "card")
    assert incidents_mod.is_ancestor(ALL_KEY, "upi")
    assert incidents_mod.is_ancestor("card", "card:card_bin6:411111")
    assert not incidents_mod.is_ancestor("card:card_bin6:411111", "card")
    assert not incidents_mod.is_ancestor("card", "upi:upi_handle:x")


def test_firing_siblings_counts_only_the_same_level():
    firing = {"card", "card:card_bin6:411111", "card:card_issuer:HDFC", "upi"}
    assert incidents_mod.firing_siblings("card:card_bin6:411111", firing) == 1
    assert incidents_mod.firing_siblings("card", firing) == 2


# -- thresholds ------------------------------------------------------------


def test_the_frozen_thresholds_match_the_architecture_document():
    assert FROZEN.window_seconds == 15 * 60
    assert FROZEN.step_seconds == 60
    assert FROZEN.min_attempts == 20
    assert FROZEN.min_absolute_excess == 0.15
    assert FROZEN.alpha == 0.001
    assert FROZEN.alpha_floor == 0.0001
    assert FROZEN.consecutive_windows == 2
    assert FROZEN.baseline_days == 7
    assert FROZEN.hour_bands_per_day == 4
    assert FROZEN.min_band_attempts == 200
    assert FROZEN.attribution_share == 0.80
    assert FROZEN.close_within_of_baseline == 0.05
    assert FROZEN.close_consecutive_windows == 4


def test_thresholds_are_immutable():
    import dataclasses

    with pytest.raises(dataclasses.FrozenInstanceError):
        FROZEN.min_attempts = 5  # type: ignore[misc]


def test_hour_bands_split_the_day_into_four():
    thresholds = Thresholds()
    assert [thresholds.hour_band(h) for h in (0, 5, 6, 11, 12, 17, 18, 23)] == [
        0, 0, 1, 1, 2, 2, 3, 3
    ]


def _seed_attempts(conn, *, start: int, count: int, method: str, fail_every: int) -> None:
    from salvage import repo

    repo.insert_customer(
        conn,
        {
            "id": "cust_1",
            "ref_hash": "h" * 64,
            "consent": 1,
            "locale": "en",
            "typical_amount": 100000,
            "created_at": 0,
        },
    )
    orders = []
    attempts = []
    for i in range(count):
        ts = start + i * 60
        failed = i % fail_every == 0
        orders.append(
            {
                "id": f"order_{i}",
                "customer_id": "cust_1",
                "amount": 100000,
                "status": "attempted",
                "source": "sim",
                "created_at": ts,
            }
        )
        attempts.append(
            {
                "id": f"pay_{i}",
                "order_id": f"order_{i}",
                "customer_id": "cust_1",
                "method": method,
                "status": "failed" if failed else "captured",
                "error_step": "payment_authorization" if failed else None,
                "created_at": ts,
                "raw_json": "{}",
            }
        )
    repo.upsert_orders_batch(conn, orders)
    repo.upsert_attempts_batch(conn, attempts)
