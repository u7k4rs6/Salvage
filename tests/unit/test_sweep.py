"""The evaluation sweep and the report generator.

Run at reduced volume with two seeds and three policies, which is enough to exercise every code
path. The full-scale sweep is `salvage eval run` and its output is docs/RESULTS.md.
"""

from __future__ import annotations

import json

import pytest

from salvage.eval.report import ReportInputs, build_report, rows_from_json, rupees
from salvage.eval.sweep import (
    aggregate,
    digests_match,
    params_with,
    sweep,
    write_results_json,
)


@pytest.fixture(scope="module")
def small_sweep(tmp_path_factory):
    import yaml

    from salvage.sim.params import PARAMS_PATH

    root = tmp_path_factory.mktemp("sweep")
    raw = yaml.safe_load(PARAMS_PATH.read_text(encoding="utf-8"))
    raw["merchant"]["customer_count"] = 400
    raw["traffic"]["attempts_per_day"] = 2400
    raw["clock"]["warmup_days"] = 2
    raw["clock"]["settle_days"] = 2
    params_path = root / "params.yaml"
    params_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    return sweep(
        scenarios=["S1"],
        seeds=[0, 1],
        policies=["B0", "B1", "B2"],
        params_path=params_path,
        run_id="test_sweep",
    )


def test_the_sweep_runs_every_combination(small_sweep):
    assert len(small_sweep.rows) == 1 * 2 * 3
    assert {row.policy for row in small_sweep.rows} == {"B0", "B1", "B2"}
    assert {row.seed for row in small_sweep.rows} == {0, 1}


def test_every_world_is_identical_across_policies(small_sweep):
    assert digests_match(small_sweep)
    assert small_sweep.notes == []
    for digests in small_sweep.digests.values():
        assert len(set(digests.values())) == 1


def test_no_policy_violations_anywhere_in_the_sweep(small_sweep):
    assert sum(row.policy_violations for row in small_sweep.rows) == 0


def test_the_eligible_population_is_identical_within_each_world(small_sweep):
    by_world: dict[tuple[str, int], set[tuple[int, int]]] = {}
    for row in small_sweep.rows:
        by_world.setdefault((row.scenario, row.seed), set()).add(
            (row.eligible_orders, row.eligible_amount)
        )
    for key, populations in by_world.items():
        assert len(populations) == 1, key


def test_aggregation_reports_a_standard_deviation_across_seeds(small_sweep):
    rows = aggregate(small_sweep.rows)
    assert {row.policy for row in rows} == {"B0", "B1", "B2"}
    for row in rows:
        assert row.seeds == 2
        assert row.mean_recovered_amount > 0
        assert row.std_recovered_amount >= 0


def test_a_single_seed_reports_zero_spread_rather_than_a_wrong_one(small_sweep):
    rows = aggregate([small_sweep.rows[0]])
    assert rows[0].seeds == 1
    assert rows[0].std_recovered_amount == 0.0


def test_the_results_json_round_trips(small_sweep, tmp_path):
    path = write_results_json(small_sweep, tmp_path)
    payload = json.loads(path.read_text())
    restored = rows_from_json(payload)
    assert restored.run_id == small_sweep.run_id
    assert len(restored.rows) == len(small_sweep.rows)
    assert restored.digests == small_sweep.digests
    assert restored.rows[0].recovered_amount == small_sweep.rows[0].recovered_amount


# -- the report ------------------------------------------------------------


def test_the_report_has_every_required_section(small_sweep):
    report = build_report(ReportInputs(main=small_sweep))
    for heading in (
        "## 1. Primary: recovered revenue over the at-risk order set",
        "### What a message costs here, and what it does not",
        "## 2. Secondary: whole-run totals",
        "## 3. Decomposition",
        "## 4. Secondary metrics",
        "## 5. Identical worlds",
        "## 6. Diagnosis ablation",
        "## 7. Detector operating envelope",
        "## 8. Peak against trough detection",
        "## 9. Sensitivity and the adversarial set",
        "## 10. Fault injection",
        "## 11. The real end-to-end run",
        "## 12. Known limitations",
    ):
        assert heading in report, heading


def test_the_report_states_what_is_unmeasured_rather_than_estimating_it(small_sweep):
    report = build_report(ReportInputs(main=small_sweep))
    assert "The LLM arm is unmeasured" in report
    assert "The agent arm has no diagnosis model" in report
    assert "has not been run" in report
    assert "There is no rules-only policy arm" in report


def test_the_report_carries_a_seed_count_on_every_table(small_sweep):
    report = build_report(ReportInputs(main=small_sweep))
    assert "across 2 seeds" in report
    # Every aggregate row names its seed count in the secondary table.
    assert "| 2 |" in report or "/2 |" in report


def test_the_report_never_invents_a_number_for_a_missing_sweep(small_sweep):
    report = build_report(ReportInputs(main=small_sweep))
    assert "It is not estimated here and no figure is given for it." in report


def test_the_primary_table_never_shows_revenue_without_contact_volume(small_sweep):
    """The old headline marked a best policy per scenario. It no longer does, because recovered
    revenue against messages sent is a trade-off and naming a winner hides the axis the reader
    should be arguing about. Every cell carries both numbers instead."""
    report = build_report(ReportInputs(main=small_sweep))
    primary = report.split("## 2.")[0]
    assert "| best |" not in primary
    # The revenue table only. The rate table below it repeats the same population as a fraction.
    revenue = primary.split("Opt-outs are counted over the whole run")[0]
    body = [line for line in revenue.splitlines() if line.startswith("| S")]
    assert body, "the primary table has at least one scenario row"
    for line in body:
        assert "msg" in line, line
    # Opt-outs are reported per arm too, in their own table, because an opt-out cannot honestly
    # be attributed to the at-risk set. Both numbers are in section 1 either way.
    assert "msg / opt-out" in primary


# -- helpers ---------------------------------------------------------------


def test_rupee_formatting_uses_indian_digit_grouping():
    assert rupees(100) == "1.00"
    assert rupees(123456) == "1,234.56"
    assert rupees(1234567890) == "1,23,45,678.90"
    assert rupees(0) == "0.00"


def test_params_with_writes_a_file_that_changes_the_params_hash(tmp_path):
    from salvage.sim.params import default_params, load

    path = params_with({"traffic.attempts_per_day": 1500}, tmp_path)
    swept = load(path)
    assert swept.attempts_per_day("S1") == 1500
    assert swept.params_hash != default_params().params_hash


def test_params_with_reaches_nested_keys(tmp_path):
    from salvage.sim.params import load

    path = params_with({"clock.settle_days": 1}, tmp_path)
    assert load(path).settle_days == 1
