"""Windowing, baselines and the four-condition test.

Architecture section 5. The detector is deterministic and contains no model call, which is the
first design rule in Architecture section 1.

Everything here reads v_payment_attempts, never payment_attempts, so ground truth cannot reach the
detector even by accident.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
from scipy.stats import binomtest

from salvage.detect.segments import (
    ALL_KEY,
    STEP_DIMENSION,
    child_key,
    is_step_key,
    keys_for_attempt,
    method_key,
    parse_key,
)
from salvage.detect.thresholds import FROZEN, Thresholds
from salvage.sim.clock import IstCalendar

_ATTEMPT_SELECT = (
    "SELECT id, method, upi_handle, card_bin, card_network, card_issuer, nb_bank, status, "
    "error_step, created_at FROM v_payment_attempts WHERE created_at >= ? AND created_at < ? "
    "ORDER BY created_at, id"
)


@dataclass
class Baseline:
    """One key's baseline failure rate, and which fallback produced it."""

    rate: float
    source: str  # band, key, method, or floor


@dataclass
class Baselines:
    by_band: dict[tuple[str, int], tuple[int, int]] = field(default_factory=dict)
    by_key: dict[str, tuple[int, int]] = field(default_factory=dict)
    by_method: dict[str, tuple[int, int]] = field(default_factory=dict)
    merchant: tuple[int, int] = (0, 0)
    thresholds: Thresholds = FROZEN

    def rate_for(self, key: str, band: int) -> Baseline:
        """Band rate, falling back to the key's overall rate, then the method-level rate.

        Exactly the ladder in Architecture section 5, plus a floor so a key with a spotless week
        does not get a baseline of zero and fire on its first failure.
        """
        thresholds = self.thresholds
        attempts, failures = self.by_band.get((key, band), (0, 0))
        if attempts >= thresholds.min_band_attempts:
            return self._floor(failures / attempts, "band")

        attempts, failures = self.by_key.get(key, (0, 0))
        if attempts >= thresholds.min_key_attempts:
            return self._floor(failures / attempts, "key")

        method = parse_key(key)[0]
        attempts, failures = self.by_method.get(method, (0, 0))
        if attempts > 0:
            return self._floor(failures / attempts, "method")

        attempts, failures = self.merchant
        if attempts > 0:
            return self._floor(failures / attempts, "merchant")
        return Baseline(thresholds.min_baseline_rate, "floor")

    def _floor(self, rate: float, source: str) -> Baseline:
        floor = self.thresholds.min_baseline_rate
        if rate < floor:
            return Baseline(floor, "floor")
        return Baseline(rate, source)


def build_baselines(
    conn, *, baseline_end: int, thresholds: Thresholds = FROZEN, calendar: IstCalendar | None = None
) -> Baselines:
    """Aggregate the trailing baseline_days before baseline_end, per key and hour band."""
    calendar = calendar or IstCalendar()
    start = baseline_end - thresholds.baseline_days * 86400

    by_band: dict[tuple[str, int], list[int]] = defaultdict(lambda: [0, 0])
    by_key: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    by_method: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    band_method_totals: dict[tuple[str, int], int] = defaultdict(int)
    merchant = [0, 0]
    step_keys: set[str] = set()

    for row in conn.execute(_ATTEMPT_SELECT, (start, baseline_end)):
        attempt = dict(row)
        band = thresholds.hour_band(calendar.hour_of_day(attempt["created_at"]))
        denominators, numerators = keys_for_attempt(attempt)
        failed = attempt["status"] == "failed"

        for key in denominators:
            by_band[(key, band)][0] += 1
            by_key[key][0] += 1
        for key in numerators:
            by_band[(key, band)][1] += 1
            by_key[key][1] += 1

        method = attempt["method"]
        by_method[method][0] += 1
        band_method_totals[(method, band)] += 1
        merchant[0] += 1
        if failed:
            by_method[method][1] += 1
            merchant[1] += 1
            step = attempt.get(STEP_DIMENSION)
            if step:
                step_keys.add(child_key(method, STEP_DIMENSION, str(step)))

    # A step key's denominator is every attempt of its method (see salvage/detect/segments.py).
    # It is filled in here rather than inside the row loop, which would otherwise cost one lookup
    # per attempt per live step of that method.
    for key in step_keys:
        method = parse_key(key)[0]
        by_key[key][0] = by_method[method][0]
        for band in range(thresholds.hour_bands_per_day):
            total = band_method_totals.get((method, band), 0)
            if total:
                by_band[(key, band)][0] = total

    return Baselines(
        by_band={k: (v[0], v[1]) for k, v in by_band.items()},
        by_key={k: (v[0], v[1]) for k, v in by_key.items()},
        by_method={k: (v[0], v[1]) for k, v in by_method.items()},
        merchant=(merchant[0], merchant[1]),
        thresholds=thresholds,
    )


@dataclass
class WindowStat:
    """One key in one window."""

    segment_key: str
    window_start: int
    window_end: int
    attempts: int
    failures: int
    baseline_rate: float
    baseline_source: str
    p_value: float

    @property
    def rate(self) -> float:
        return self.failures / self.attempts if self.attempts else 0.0

    @property
    def excess_failures(self) -> float:
        return max(0.0, self.failures - self.baseline_rate * self.attempts)


class WindowCounters:
    """Per-minute attempt and failure counts per key, with prefix sums for window queries.

    Built in one pass over the attempts. A window query is then two array lookups rather than a
    scan, which is what keeps 1,440 evaluations across roughly 70 keys under a second.
    """

    def __init__(self, start: int, end: int, step_seconds: int) -> None:
        self.start = start
        self.step = step_seconds
        self.minutes = max(1, (end - start + step_seconds - 1) // step_seconds)
        self._attempts: dict[str, np.ndarray] = {}
        self._failures: dict[str, np.ndarray] = {}
        self._cum_attempts: dict[str, np.ndarray] = {}
        self._cum_failures: dict[str, np.ndarray] = {}

    def _array(self, store: dict[str, np.ndarray], key: str) -> np.ndarray:
        array = store.get(key)
        if array is None:
            array = np.zeros(self.minutes, dtype=np.int64)
            store[key] = array
        return array

    def bucket(self, ts: int) -> int:
        return (ts - self.start) // self.step

    def add(self, ts: int, denominators: list[str], numerators: list[str]) -> None:
        index = self.bucket(ts)
        if index < 0 or index >= self.minutes:
            return
        for key in denominators:
            self._array(self._attempts, key)[index] += 1
        for key in numerators:
            self._array(self._failures, key)[index] += 1

    def finalise(self) -> None:
        """Fill step keys' denominators and compute prefix sums."""
        for key in list(self._failures):
            if key not in self._attempts and is_step_key(key):
                method = parse_key(key)[0]
                method_attempts = self._attempts.get(method)
                if method_attempts is not None:
                    self._attempts[key] = method_attempts
        for key, array in self._attempts.items():
            self._cum_attempts[key] = np.concatenate(([0], np.cumsum(array)))
        for key in self._attempts:
            failures = self._failures.get(key)
            if failures is None:
                failures = np.zeros(self.minutes, dtype=np.int64)
                self._failures[key] = failures
            self._cum_failures[key] = np.concatenate(([0], np.cumsum(failures)))

    @property
    def keys(self) -> list[str]:
        return list(self._cum_attempts)

    def window(self, key: str, window_start: int, window_end: int) -> tuple[int, int]:
        lo = max(0, self.bucket(window_start))
        hi = min(self.minutes, self.bucket(window_end))
        if hi <= lo:
            return 0, 0
        cum_a = self._cum_attempts.get(key)
        if cum_a is None:
            return 0, 0
        cum_f = self._cum_failures[key]
        return int(cum_a[hi] - cum_a[lo]), int(cum_f[hi] - cum_f[lo])


def build_counters(
    conn, *, start: int, end: int, thresholds: Thresholds = FROZEN
) -> WindowCounters:
    counters = WindowCounters(start, end, thresholds.step_seconds)
    for row in conn.execute(_ATTEMPT_SELECT, (start, end)):
        attempt = dict(row)
        denominators, numerators = keys_for_attempt(attempt)
        counters.add(attempt["created_at"], denominators, numerators)
    counters.finalise()
    return counters


def binomial_p_value(failures: int, attempts: int, baseline_rate: float) -> float:
    """One-sided binomial test of k failures in n against p0.

    scipy is used for this and nothing else (Architecture section 14). The guards below avoid
    calling it in the two cases where the answer is known and scipy would either raise or waste
    time.
    """
    if attempts <= 0:
        return 1.0
    if failures <= baseline_rate * attempts:
        return 1.0
    p0 = min(max(baseline_rate, 1e-12), 1.0 - 1e-12)
    return float(binomtest(failures, attempts, p0, alternative="greater").pvalue)


def alpha_for(live_keys: int, thresholds: Thresholds = FROZEN) -> float:
    """Bonferroni across the number of live keys, floored.

    Architecture section 5: "p-value below 0.001 (Bonferroni across the number of live keys,
    capped at 0.0001)". Read as: divide 0.001 by the number of live keys, and do not let the
    result fall below 0.0001.
    """
    if live_keys <= 1:
        return thresholds.alpha
    return max(thresholds.alpha_floor, thresholds.alpha / live_keys)


def evaluate_window(
    counters: WindowCounters,
    baselines: Baselines,
    *,
    window_start: int,
    window_end: int,
    calendar: IstCalendar,
    thresholds: Thresholds = FROZEN,
) -> tuple[list[WindowStat], list[WindowStat]]:
    """(stats for every live key, stats for keys passing conditions 1 to 3).

    A key is live when it has at least min_attempts in the window. The Bonferroni correction is
    computed from the number of live keys in this window, which is what "across the number of live
    keys" means.
    """
    band = thresholds.hour_band(calendar.hour_of_day(window_end - 1))
    live: list[WindowStat] = []

    for key in counters.keys:
        attempts, failures = counters.window(key, window_start, window_end)
        if attempts < thresholds.min_attempts:
            continue
        baseline = baselines.rate_for(key, band)
        live.append(
            WindowStat(
                segment_key=key,
                window_start=window_start,
                window_end=window_end,
                attempts=attempts,
                failures=failures,
                baseline_rate=baseline.rate,
                baseline_source=baseline.source,
                p_value=math.nan,
            )
        )

    alpha = alpha_for(len(live), thresholds)
    passing: list[WindowStat] = []
    for stat in live:
        if stat.rate - stat.baseline_rate < thresholds.min_absolute_excess:
            stat.p_value = 1.0
            continue
        stat.p_value = binomial_p_value(stat.failures, stat.attempts, stat.baseline_rate)
        if stat.p_value < alpha:
            passing.append(stat)
    return live, passing


def method_keys_of(keys: list[str]) -> set[str]:
    return {method_key(parse_key(key)[0]) for key in keys if key != ALL_KEY}
