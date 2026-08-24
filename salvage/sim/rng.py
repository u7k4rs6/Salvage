"""Seeded random streams.

Architecture section 9: "per-order counterfactual outcomes computed with a shared random stream
per seed so that agent and baselines face the same customers."

The mechanism: every source of randomness draws from a named substream derived from the seed. A
substream's sequence depends only on (seed, name) and on how many values have been drawn from
that substream, never on what any other substream did. So adding a policy that draws from
"policy" in M2 cannot shift the values that "customers", "arrivals" or "response" produce, and
the agent and every baseline see identical customers, identical arrival times, identical method
choices and identical organic outcomes.

The rule that keeps this true: policy-dependent code must never draw from a world substream.
World substreams are the four named in WORLD_STREAMS.
"""

from __future__ import annotations

import hashlib

import numpy as np

# Substreams whose values must be identical across policies for the same seed.
WORLD_STREAMS = ("customers", "arrivals", "attempts", "response", "intervention")


def _stream_id(name: str) -> int:
    """Stable 32-bit id for a stream name. Python's hash() is salted per process, so it cannot
    be used here: the same name must give the same stream in every run on every machine."""
    return int.from_bytes(hashlib.sha256(name.encode()).digest()[:4], "big")


def substream(seed: int, name: str) -> np.random.Generator:
    """A generator for one named stream of one seed."""
    return np.random.default_rng([int(seed), _stream_id(name)])


def order_stream(seed: int, name: str, order_index: int) -> np.random.Generator:
    """A generator for one order's draws inside one named stream.

    Per-order rather than sequential, and this matters. An order that a recovery link pays never
    makes the organic retries it would have made, so a stream consumed in sequence would shift
    every later order's draws the moment a policy acted, and the agent and the baselines would
    stop facing the same customers. Keying on the order index makes an order's counterfactual
    depend on that order alone, whatever any policy did to any other order.

    The order index is assigned by the traffic generator in world order, so it is the same for
    every policy at a given seed.
    """
    return np.random.default_rng([int(seed), _stream_id(name), int(order_index)])


class Streams:
    """The set of substreams for one run. Created once by the runner."""

    def __init__(self, seed: int) -> None:
        self.seed = int(seed)
        self._streams: dict[str, np.random.Generator] = {}

    def __getitem__(self, name: str) -> np.random.Generator:
        if name not in self._streams:
            self._streams[name] = substream(self.seed, name)
        return self._streams[name]

    @property
    def customers(self) -> np.random.Generator:
        return self["customers"]

    @property
    def arrivals(self) -> np.random.Generator:
        return self["arrivals"]

    @property
    def attempts(self) -> np.random.Generator:
        return self["attempts"]

    @property
    def response(self) -> np.random.Generator:
        return self["response"]


def weighted_choice_table(shares: list[float]) -> np.ndarray:
    """Cumulative table for repeated weighted sampling. Normalises, so callers do not have to."""
    array = np.asarray(shares, dtype=float)
    if np.any(array < 0):
        raise ValueError("shares must be non-negative")
    total = array.sum()
    if total <= 0:
        raise ValueError("shares must not all be zero")
    return np.cumsum(array / total)


def pick(table: np.ndarray, draw: float) -> int:
    """Index selected by a uniform draw against a cumulative table."""
    return int(np.searchsorted(table, draw, side="right"))
