"""Shared fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from salvage.db import open_migrated
from salvage.sim.params import PARAMS_PATH


@pytest.fixture
def conn(tmp_path):
    connection = open_migrated(tmp_path / "test.db")
    yield connection
    connection.close()


@pytest.fixture
def small_params_path(tmp_path) -> Path:
    """The real params.yaml with the volume knobs turned down.

    Tests assert on structure and behaviour, not on scale, and a full eight-day run at 12,000
    attempts a day takes about three seconds. Only the four volume keys change; every
    distribution, error profile and fault stays exactly as shipped, so a test that passes here is
    testing the real instrument.
    """
    raw = yaml.safe_load(PARAMS_PATH.read_text(encoding="utf-8"))
    raw["merchant"]["customer_count"] = 400
    raw["traffic"]["attempts_per_day"] = 2400
    raw["clock"]["warmup_days"] = 2
    raw["clock"]["eval_days"] = 1
    path = tmp_path / "params_small.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path
