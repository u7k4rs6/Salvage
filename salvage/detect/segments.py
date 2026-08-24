"""Segment keys.

Architecture section 5: "Segment keys are computed for every attempt: method,
method:upi_handle, method:card_network, method:card_issuer, method:card_bin6, method:nb_bank, and
error_step crossed with method."

Two additions to that list, both recorded in docs/BUILD_LOG.md:

  ALL_KEY, a merchant-wide key. Section 5 also requires that "a gateway-wide fault produces one
  incident, not twenty", and a fault spanning every method has no key in the published list to be
  attributed to. Without a root there is nothing coarser than "upi" and S3 would open four
  incidents.

  The denominator for an error_step key is every attempt of that method, not just the failures at
  that step. A successful payment has no error_step, so a key whose denominator was "attempts with
  this step" would have a failure rate of exactly 1.0 always and could never be tested. Reading it
  as "share of this method's attempts that failed at this step" gives a rate with a meaningful
  baseline.
"""

from __future__ import annotations

from typing import Any

ALL_KEY = "all"

# Dimensions on an attempt row that produce a "method plus instrument" key. Order matters: it is
# the tie-break when several children of a method explain the same excess, finest first.
INSTRUMENT_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("card_bin6", "card_bin"),
    ("upi_handle", "upi_handle"),
    ("nb_bank", "nb_bank"),
    ("card_issuer", "card_issuer"),
    ("card_network", "card_network"),
)

STEP_DIMENSION = "error_step"


def method_key(method: str) -> str:
    return method


def child_key(method: str, dimension: str, value: str) -> str:
    return f"{method}:{dimension}:{value}"


def parse_key(key: str) -> tuple[str, str | None, str | None]:
    """(method, dimension, value). The root and a bare method key have no dimension."""
    if key == ALL_KEY:
        return ALL_KEY, None, None
    parts = key.split(":", 2)
    if len(parts) == 1:
        return parts[0], None, None
    return parts[0], parts[1], parts[2]


def parent_key(key: str) -> str | None:
    """The key one level up. A child's parent is its method; a method's parent is the root."""
    method, dimension, _ = parse_key(key)
    if key == ALL_KEY:
        return None
    if dimension is None:
        return ALL_KEY
    return method


def is_step_key(key: str) -> bool:
    return parse_key(key)[1] == STEP_DIMENSION


def keys_for_attempt(attempt: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(denominator keys, numerator keys) for one attempt.

    Denominator keys are the keys this attempt counts towards as an attempt. Numerator keys are
    the keys it counts towards as a failure, and are a subset of the denominators except for the
    step key, which is only a numerator key when the attempt failed at that step.

    Returning both lists rather than one keeps the error_step asymmetry explicit: the step key's
    denominator is the method's attempts, so the attempt always counts in the method's step keys'
    denominators, but only the attempt that failed at that step counts in its numerator.
    """
    method = attempt.get("method")
    if not method:
        return [], []

    failed = attempt.get("status") == "failed"
    denominators = [ALL_KEY, method_key(method)]
    for dimension, column in INSTRUMENT_DIMENSIONS:
        value = attempt.get(column)
        if value:
            denominators.append(child_key(method, dimension, str(value)))

    numerators = list(denominators) if failed else []
    if failed:
        step = attempt.get(STEP_DIMENSION)
        if step:
            numerators.append(child_key(method, STEP_DIMENSION, str(step)))
    return denominators, numerators


def step_denominator_keys(attempt: dict[str, Any], live_steps: set[str]) -> list[str]:
    """Step keys this attempt counts towards as a denominator.

    Every attempt of a method counts in the denominator of every step key of that method, because
    the rate a step key measures is "share of this method's attempts that failed at this step".
    live_steps is the set of step keys seen anywhere in the run, so the denominator is only kept
    for steps that actually occur.
    """
    method = attempt.get("method")
    if not method:
        return []
    prefix = f"{method}:{STEP_DIMENSION}:"
    return [key for key in live_steps if key.startswith(prefix)]
