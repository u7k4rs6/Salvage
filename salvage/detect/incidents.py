"""Incident attribution, open, close, and at-risk revenue.

Architecture section 5:

  Attribution: when several keys fire together (all UPI handles at once, say), the incident is
  attributed to the coarsest key that explains at least 80 percent of the excess failures, so a
  gateway-wide fault produces one incident, not twenty. Child keys are recorded inside the
  incident as affected scope.

  Incident close: the key's rate is back within 0.05 of baseline for four consecutive windows and
  every recovery case is terminal.

  At-risk revenue: sum of orders.amount for attempts inside the incident window whose order is
  unpaid at evaluation time.

How the attribution sentence is read, and why. Taken literally, "the coarsest key that explains at
least 80 percent of the excess failures" attributes S1 to `upi`: when one UPI handle fails, the
method key `upi` also fires and it explains 100 percent of the excess, and it is coarser than the
handle key. That contradicts docs/01_PRD.md section 10, where S1's correct behaviour is to steer
away from one handle while the others keep working. The implemented reading keeps the sentence's
purpose, which is one incident per fault rather than twenty, and resolves the ambiguity by
descending: start at the coarsest firing key, and while a single child accounts for at least 80
percent of that key's excess failures, move down to it. A single-handle outage lands on the
handle; a gateway-wide fault has no dominant child at any level and stays at the root, producing
one incident. Recorded in docs/BUILD_LOG.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from salvage import repo
from salvage.detect.monitor import WindowStat
from salvage.detect.segments import ALL_KEY, INSTRUMENT_DIMENSIONS, parse_key
from salvage.detect.thresholds import FROZEN, Thresholds

# Tie-break order when several children of a method explain the same excess: finest description
# first. Two dimensions can cover exactly the same attempts (one BIN per issuer, for instance),
# and a stable order stops the attributed segment from depending on dict iteration.
_DIMENSION_ORDER = {name: index for index, (name, _) in enumerate(INSTRUMENT_DIMENSIONS)}


@dataclass
class FiringGroup:
    """One fault's worth of firing keys."""

    root: str
    attributed: str
    scope: list[str] = field(default_factory=list)
    excess: float = 0.0
    # How many firing instrument keys sit directly below the attributed key. Two or more means the
    # fault genuinely spans that level rather than sitting in one child of it, which is what
    # justifies widening an open incident onto this key.
    breadth: int = 0


def _children_of(key: str, stats: dict[str, WindowStat]) -> list[str]:
    """Firing keys one level below `key`.

    The root's children are the method keys. A method's children are its instrument and step
    keys. Step keys are children for scope but are never descended into: `upi:error_step:X` says
    where a failure happened, not which customers were affected, and steering needs an
    instrument.
    """
    if key == ALL_KEY:
        return [k for k in stats if k != ALL_KEY and parse_key(k)[1] is None]
    method, dimension, _ = parse_key(key)
    if dimension is not None:
        return []
    return [k for k in stats if k != key and parse_key(k)[0] == method and parse_key(k)[1]]


def _descendable(children: list[str]) -> list[str]:
    """Children attribution may move down to.

    Everything except step keys. A step key names where in the flow a payment died, not which
    customers were affected, and an incident's segment has to be something the executor can steer
    away from.
    """
    return [key for key in children if parse_key(key)[1] != "error_step"]


def _sort_key(key: str, stats: dict[str, WindowStat]) -> tuple[int, int, str]:
    stat = stats[key]
    dimension = parse_key(key)[1] or ""
    return (stat.attempts, _DIMENSION_ORDER.get(dimension, 99), key)


def attribute(
    passing: list[WindowStat], thresholds: Thresholds = FROZEN
) -> list[FiringGroup]:
    """Group the firing keys into one group per fault and choose each group's segment."""
    if not passing:
        return []
    stats = {stat.segment_key: stat for stat in passing}

    stats, roots = _roots(stats)

    groups: list[FiringGroup] = []
    for root in roots:
        attributed = root
        while True:
            children = _descendable(_children_of(attributed, stats))
            if not children:
                break
            parent_excess = stats[attributed].excess_failures
            if parent_excess <= 0:
                break
            dominant = [
                key
                for key in children
                if stats[key].excess_failures >= thresholds.attribution_share * parent_excess
            ]
            if not dominant:
                break
            attributed = min(dominant, key=lambda k: _sort_key(k, stats))

        scope = sorted({attributed, *_scope_below(attributed, stats)})
        groups.append(
            FiringGroup(
                root=root,
                attributed=attributed,
                scope=scope,
                excess=stats[attributed].excess_failures,
                breadth=len(_descendable(_children_of(attributed, stats))),
            )
        )
    return groups


def _synthetic_parent(method: str, children: list[str], stats: dict[str, WindowStat]) -> WindowStat:
    """Stand-in for a method key that is not firing while its children are.

    A card BIN outage makes the BIN, the issuer and the network keys fire several minutes before
    the method key crosses the absolute-excess threshold, because the method key's rate is diluted
    by four healthy BIN ranges. Without a parent to start from, attribution would have to pick one
    of the three firing children by some arbitrary rule, and the arbitrary rule it had picked the
    widest-excess one, which is a tie between them and fell through to alphabetical order. Rooting
    at a stand-in for the method and then descending applies the same 80 percent rule as
    everywhere else, and lands on the narrowest key that explains the excess.
    """
    coarsest = max(children, key=lambda key: (stats[key].attempts, key))
    template = stats[coarsest]
    return WindowStat(
        segment_key=method,
        window_start=template.window_start,
        window_end=template.window_end,
        attempts=template.attempts,
        failures=template.failures,
        baseline_rate=template.baseline_rate,
        baseline_source="synthetic",
        p_value=template.p_value,
    )


def _roots(stats: dict[str, WindowStat]) -> tuple[dict[str, WindowStat], list[str]]:
    """Where attribution starts, one root per fault.

    The merchant-wide key only becomes a root when at least two method keys are firing with it.
    ALL_KEY is an addition to the published key list (see salvage/detect/segments.py) and it exists
    for one purpose: to give a fault that spans methods somewhere to be attributed. A merchant-wide
    key firing on its own is not that fault, it is a small window in the overnight trough where
    ALL_KEY is the only key with enough attempts to be tested at all. Requiring corroboration ties
    the key to the reason it was added. See docs/BUILD_LOG.md.

    A step key is never a root. `upi:error_step:payment_debit_request` says where in the flow a
    failure happened, not which customers were affected, and an incident's segment has to be
    something the executor can steer away from. A step key is a root only when nothing else in
    that method is firing, which is better than discarding the only evidence there is.
    """
    method_keys = [key for key in stats if key != ALL_KEY and parse_key(key)[1] is None]
    if ALL_KEY in stats and len(method_keys) >= 2:
        return stats, [ALL_KEY]

    by_method: dict[str, list[str]] = {}
    for key in stats:
        if key == ALL_KEY:
            continue
        by_method.setdefault(parse_key(key)[0], []).append(key)

    stats = dict(stats)
    roots: list[str] = []
    for method, keys in sorted(by_method.items()):
        if method in stats:
            roots.append(method)
            continue
        instruments = _descendable(keys)
        if instruments:
            stats[method] = _synthetic_parent(method, instruments, stats)
            roots.append(method)
        # Only step keys firing for this method produces no root, so no incident opens on a step
        # key. A step key names where in the flow a payment died; an incident's segment has to be
        # something the executor can steer away from, and "card payments that failed at
        # authentication" is not an instrument. The step keys are the most sensitive detector of a
        # BIN outage, because their baseline is small, so this costs one or two minutes of
        # detection latency and buys an attributed segment that names the failing instrument.
    return stats, roots


def same_family(left: str, right: str) -> bool:
    """Whether two segment keys could describe the same fault.

    The merchant-wide key is in every family, because a fault first seen on one method and later
    seen merchant-wide is one fault. Two keys under the same method are in the same family. Two
    keys under different methods are not.
    """
    if left == ALL_KEY or right == ALL_KEY:
        return True
    return parse_key(left)[0] == parse_key(right)[0]


def firing_siblings(segment_key: str, firing_keys: set[str]) -> int:
    """How many keys at the same level as `segment_key` are firing.

    Used to decide whether an open incident should widen. One BIN range failing makes the card
    method key fire too, because 30 percent of card traffic is dying; that is not a reason to
    relabel the incident as "all cards", and the giveaway is that only one BIN key is firing. When
    several siblings at the incident's own level are failing, the fault really is one level up.
    """
    if segment_key == ALL_KEY:
        return 0
    method, dimension, _ = parse_key(segment_key)
    if dimension is None:
        return sum(1 for key in firing_keys if key != ALL_KEY and parse_key(key)[1] is None)
    return sum(
        1
        for key in firing_keys
        if parse_key(key)[0] == method and parse_key(key)[1] == dimension
    )


def is_ancestor(candidate: str, key: str) -> bool:
    """Whether `candidate` is strictly coarser than `key` in the segment hierarchy."""
    if candidate == key:
        return False
    if candidate == ALL_KEY:
        return True
    if key == ALL_KEY:
        return False
    return parse_key(candidate)[1] is None and parse_key(key)[0] == candidate


def _scope_below(key: str, stats: dict[str, WindowStat]) -> list[str]:
    """Every firing key at or below `key`, including step keys, for the affected scope."""
    if key == ALL_KEY:
        return [k for k in stats]
    method, dimension, value = parse_key(key)
    if dimension is None:
        return [k for k in stats if parse_key(k)[0] == method]
    # A specific instrument. Its scope is itself plus the method's step keys, which describe where
    # in the flow the failures land.
    return [k for k in stats if parse_key(k)[0] == method and parse_key(k)[1] == "error_step"]


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def incident_id_for(segment_key: str, opened_at: int) -> str:
    safe = segment_key.replace(":", "_")
    return f"inc_{safe}_{opened_at}"


def at_risk_amount(conn, *, segment_key: str, window_start: int, evaluated_at: int) -> int:
    """Sum of order amounts for failed attempts in the incident window whose order is still
    unpaid at evaluation time.

    The join goes through v_payment_attempts and v_orders, so no ground truth is touched. An
    order is counted once even if it has several failed attempts inside the window.
    """
    method, dimension, value = parse_key(segment_key)
    conditions = ["a.status = 'failed'", "a.created_at >= ?", "a.created_at < ?"]
    args: list[object] = [window_start, evaluated_at]
    if segment_key != ALL_KEY:
        conditions.append("a.method = ?")
        args.append(method)
    if dimension == "upi_handle":
        conditions.append("a.upi_handle = ?")
        args.append(value)
    elif dimension == "card_bin6":
        conditions.append("a.card_bin = ?")
        args.append(value)
    elif dimension == "card_issuer":
        conditions.append("a.card_issuer = ?")
        args.append(value)
    elif dimension == "card_network":
        conditions.append("a.card_network = ?")
        args.append(value)
    elif dimension == "nb_bank":
        conditions.append("a.nb_bank = ?")
        args.append(value)
    elif dimension == "error_step":
        conditions.append("a.error_step = ?")
        args.append(value)

    row = conn.execute(
        "SELECT COALESCE(SUM(o.amount), 0) AS total FROM v_orders o WHERE o.id IN ("
        "  SELECT DISTINCT a.order_id FROM v_payment_attempts a WHERE " + " AND ".join(conditions) +
        ") AND o.paid_at IS NULL",
        tuple(args),
    ).fetchone()
    return int(row["total"])


def open_incident(
    conn, *, segment_key: str, opened_at: int, scope: list[str], at_risk: int
) -> str:
    incident_id = incident_id_for(segment_key, opened_at)
    repo.insert_incident(
        conn,
        {
            "id": incident_id,
            "segment_key": segment_key,
            "opened_at": opened_at,
            "closed_at": None,
            "at_risk_amount": at_risk,
            "rules_cause": None,
            "llm_cause": None,
            "root_cause": None,
            "confidence": None,
            "plan_json": None,
            "status": "open",
            "affected_scope_json": json.dumps(sorted(scope)),
        },
    )
    return incident_id


def close_incident(conn, incident_id: str, closed_at: int) -> None:
    """Close an incident.

    Architecture section 5 also requires every recovery case to be terminal. M1 creates no cases,
    so the check below is vacuously true today; it is written now so M2 does not have to remember
    to add it.
    """
    open_cases = conn.execute(
        "SELECT COUNT(*) AS n FROM recovery_cases WHERE incident_id = ? "
        "AND outcome IS NULL",
        (incident_id,),
    ).fetchone()["n"]
    if open_cases:
        return
    repo.close_incident(conn, incident_id, closed_at)
