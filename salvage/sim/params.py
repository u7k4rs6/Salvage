"""Loader for sim/params.yaml.

Architecture section 13 does not list this file. It exists so that nothing in salvage/sim/ reads
raw dict keys by hand and so the parameter file has exactly one parser. See docs/BUILD_LOG.md.

The loader validates that the file is internally consistent: shares sum to one, weights are
positive, every published error value in the file is a value Razorpay actually publishes. That
last check is the one that matters, because a typo in a reason name would otherwise sail through
into the results.
"""

from __future__ import annotations

import functools
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from salvage import taxonomy

PARAMS_PATH = Path(__file__).resolve().parent / "params.yaml"

_SHARE_TOLERANCE = 1e-9


class ParamsError(ValueError):
    """The parameter file is inconsistent. Raised at load time, never swallowed."""


@dataclass(frozen=True)
class ErrorProfileEntry:
    reason: str
    source: str
    step: str
    weight: float


@dataclass(frozen=True)
class Fault:
    selector: dict[str, str]
    start_minute: int
    duration_minutes: int
    failure_rate: float
    truth_cause: str
    error_profile: tuple[ErrorProfileEntry, ...]
    additive: bool = False
    sets_config_changed_flag: bool = False

    def matches(self, attempt: dict[str, Any]) -> bool:
        """An empty selector matches everything, which is how S3 spans all methods."""
        return all(attempt.get(key) == expected for key, expected in self.selector.items())


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    description: str
    faults: tuple[Fault, ...]
    implemented: bool = True
    # Per-scenario parameter overrides, for example a different attempts_per_day. M3's volume
    # sweep sets this, which is why traffic volume is a scenario parameter and not a constant.
    overrides: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Params:
    raw: dict[str, Any]
    path: Path
    scenarios: dict[str, Scenario] = field(default_factory=dict)

    # -- convenience accessors, so callers never index raw dicts ----------

    @property
    def epoch(self) -> int:
        return int(self.raw["clock"]["epoch_unix"])

    @property
    def ist_offset(self) -> int:
        return int(self.raw["clock"]["ist_offset_seconds"])

    @property
    def warmup_days(self) -> int:
        return int(self.raw["clock"]["warmup_days"])

    @property
    def eval_days(self) -> int:
        return int(self.raw["clock"]["eval_days"])

    @property
    def settle_days(self) -> int:
        """Days after the evaluation day in which no new orders are created.

        Organic retries and recovery-link payments scheduled during the evaluation day land here.
        Without the tail, the last evening's failures would count as unrecovered purely because
        the simulation stopped.
        """
        return int(self.raw["clock"].get("settle_days", 0))

    @property
    def fault_variants(self) -> dict[str, Any]:
        return self.raw.get("fault_variants", {})

    def variant(self, name: str) -> dict[str, Any]:
        try:
            return self.fault_variants[name]
        except KeyError:
            known = ", ".join(sorted(self.fault_variants))
            raise ParamsError(f"unknown fault variant {name!r}; known: {known}") from None

    def attempts_per_day(self, scenario_id: str | None = None) -> int:
        """Traffic volume, which is a scenario parameter rather than a constant.

        M3 runs a volume sweep, so nothing in salvage/sim/ may read
        traffic.attempts_per_day directly.
        """
        base = int(self.traffic["attempts_per_day"])
        if scenario_id is None:
            return base
        overrides = self.scenarios[scenario_id].overrides
        return int(overrides.get("traffic", {}).get("attempts_per_day", base))

    @property
    def merchant(self) -> dict[str, Any]:
        return self.raw["merchant"]

    @property
    def traffic(self) -> dict[str, Any]:
        return self.raw["traffic"]

    @property
    def organic(self) -> dict[str, Any]:
        return self.raw["organic"]

    @property
    def response(self) -> dict[str, Any]:
        return self.raw["response"]

    @property
    def fault_start_jitter_minutes(self) -> int:
        return int(self.raw["fault_start_jitter_minutes"])

    @property
    def params_hash(self) -> str:
        """Hash of the file as bytes. Stored on every sim run so a result names its instrument."""
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def scenario(self, scenario_id: str) -> Scenario:
        try:
            return self.scenarios[scenario_id]
        except KeyError:
            known = ", ".join(sorted(self.scenarios))
            raise ParamsError(f"unknown scenario {scenario_id!r}; known: {known}") from None

    def organic_profile(self, method: str) -> tuple[ErrorProfileEntry, ...]:
        return _parse_profile(self.organic["error_profiles"][method])


def _parse_profile(entries: list[dict[str, Any]]) -> tuple[ErrorProfileEntry, ...]:
    return tuple(
        ErrorProfileEntry(
            reason=str(entry["reason"]),
            source=str(entry["source"]),
            step=str(entry["step"]),
            weight=float(entry["weight"]),
        )
        for entry in entries
    )


def _check_shares(items: list[dict[str, Any]], label: str) -> None:
    total = sum(float(item["share"]) for item in items)
    if abs(total - 1.0) > 1e-6:
        raise ParamsError(f"{label} shares sum to {total}, expected 1.0")


def _check_profile(profile: tuple[ErrorProfileEntry, ...], label: str) -> None:
    if not profile:
        raise ParamsError(f"{label} has an empty error profile")
    for entry in profile:
        if entry.weight <= 0:
            raise ParamsError(f"{label}: weight for {entry.reason} must be positive")
        # The reason and step must be values Razorpay publishes. The source is allowed to be an
        # unpublished value, because Razorpay itself emits one (see salvage/taxonomy.py), but it
        # must at least be a source the taxonomy knows about.
        if not taxonomy.is_known_reason(entry.reason):
            raise ParamsError(f"{label}: {entry.reason!r} is not a published Razorpay reason")
        if not taxonomy.is_known_step(entry.step):
            raise ParamsError(f"{label}: {entry.step!r} is not a published Razorpay step")
        if not taxonomy.is_known_source(entry.source):
            raise ParamsError(f"{label}: {entry.source!r} is not a known Razorpay source")


def _parse_scenarios(raw: dict[str, Any]) -> dict[str, Scenario]:
    scenarios: dict[str, Scenario] = {}
    for scenario_id, body in raw["scenarios"].items():
        faults = []
        for index, fault in enumerate(body.get("faults") or []):
            profile = _parse_profile(fault["error_profile"])
            _check_profile(profile, f"{scenario_id} fault {index}")
            rate = float(fault["failure_rate"])
            if not 0.0 <= rate <= 1.0:
                raise ParamsError(f"{scenario_id} fault {index}: failure_rate out of range")
            faults.append(
                Fault(
                    selector={str(k): str(v) for k, v in (fault.get("selector") or {}).items()},
                    start_minute=int(fault["start_minute"]),
                    duration_minutes=int(fault["duration_minutes"]),
                    failure_rate=rate,
                    truth_cause=str(fault["truth_cause"]),
                    error_profile=profile,
                    additive=bool(fault.get("additive", False)),
                    sets_config_changed_flag=bool(fault.get("sets_config_changed_flag", False)),
                )
            )
        scenarios[scenario_id] = Scenario(
            scenario_id=scenario_id,
            description=str(body.get("description", "")).strip(),
            faults=tuple(faults),
            implemented=bool(body.get("implemented", True)),
            overrides=dict(body.get("overrides") or {}),
        )
    return scenarios


def validate(raw: dict[str, Any]) -> None:
    traffic = raw["traffic"]
    total = sum(float(v) for v in traffic["method_mix"].values())
    if abs(total - 1.0) > 1e-6:
        raise ParamsError(f"method_mix sums to {total}, expected 1.0")
    _check_shares(traffic["upi_handles"], "upi_handles")
    _check_shares(traffic["card_bins"], "card_bins")
    _check_shares(traffic["netbanking_banks"], "netbanking_banks")
    _check_shares(traffic["wallets"], "wallets")

    hours = {int(h) for h in traffic["diurnal_weights"]}
    if hours != set(range(24)):
        raise ParamsError("diurnal_weights must have exactly the 24 hours 0 to 23")
    if any(float(w) <= 0 for w in traffic["diurnal_weights"].values()):
        raise ParamsError("diurnal_weights must all be positive")

    for method, profile in raw["organic"]["error_profiles"].items():
        _check_profile(_parse_profile(profile), f"organic {method}")
    for method in raw["traffic"]["method_mix"]:
        if method not in raw["organic"]["failure_rate_by_method"]:
            raise ParamsError(f"organic failure rate missing for method {method!r}")
        if method not in raw["organic"]["error_profiles"]:
            raise ParamsError(f"organic error profile missing for method {method!r}")

    bands = raw["response"]["p_organic_by_value_band"]
    if bands[-1]["max_paise"] is not None:
        raise ParamsError("the last p_organic value band must have max_paise: null")


def load(path: Path | str | None = None) -> Params:
    path = Path(path) if path else PARAMS_PATH
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    validate(raw)
    return Params(raw=raw, path=path, scenarios=_parse_scenarios(raw))


@functools.lru_cache(maxsize=1)
def default_params() -> Params:
    return load()
