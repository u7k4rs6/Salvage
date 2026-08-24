"""Calibration: the exit criteria from docs/01_PRD.md section 13, at full simulator scale.

These are slower than the unit tests (about four seconds per run) because they use the shipped
sim/params.yaml, not a reduced one. That is the point: the calibration numbers in
docs/BUILD_LOG.md are only meaningful against the instrument that ships.

One seed per scenario runs here. The full five-seed table is produced by
`salvage detect calibrate --seeds 0..4` and recorded in docs/BUILD_LOG.md.
"""

from __future__ import annotations

import pytest

from salvage.detect.calibrate import format_table, run_one
from salvage.detect.thresholds import FROZEN

# G1 in docs/01_PRD.md section 3.
MAX_TIME_TO_DETECT_MINUTES = 15
MAX_FALSE_INCIDENTS_PER_DAY = 0.2

EXPECTED_SEGMENT = {
    "S1": "upi:upi_handle:okhdfcbank",
    "S2": "card:card_bin6:411111",
    "S3": "all",
    "S4": "netbanking",
}


@pytest.mark.parametrize("scenario", ["S1", "S2", "S3", "S4"])
def test_fault_is_detected_within_fifteen_sim_minutes(scenario, tmp_path):
    row = run_one(scenario, seed=1, workdir=tmp_path)
    assert row.detected, f"{scenario} was not detected at all"
    assert row.time_to_detect_minutes < MAX_TIME_TO_DETECT_MINUTES
    # One fault produces one incident (Architecture section 5).
    assert row.incidents_opened == 1
    assert row.detected_segment == EXPECTED_SEGMENT[scenario]


def test_s0_stays_quiet(tmp_path):
    row = run_one("S0", seed=1, workdir=tmp_path)
    assert row.incidents_opened == 0
    assert row.false_incidents_per_day < MAX_FALSE_INCIDENTS_PER_DAY


def test_calibration_table_renders(tmp_path):
    rows = [run_one("S0", seed=1, workdir=tmp_path), run_one("S1", seed=1, workdir=tmp_path)]
    table = format_table(rows)
    assert "scenario" in table
    assert "S1 to S4" in table
    assert "S0 all seeds" in table


def test_thresholds_used_by_calibration_are_the_frozen_ones():
    import inspect

    from salvage.detect import calibrate as calibrate_mod

    signature = inspect.signature(calibrate_mod.run_one)
    assert signature.parameters["thresholds"].default is FROZEN
