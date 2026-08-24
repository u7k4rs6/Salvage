"""The detector loop.

Walks the evaluation window minute by minute, evaluates every segment key over the trailing 15
simulated minutes, opens incidents when the four conditions hold, and closes them when the key
recovers.

Architecture section 13 does not name this file; monitor.py holds the statistics and incidents.py
holds attribution and persistence, and this is the loop that drives both. See docs/BUILD_LOG.md.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from salvage.detect import incidents as incidents_mod
from salvage.detect.monitor import (
    Baselines,
    WindowStat,
    build_baselines,
    build_counters,
    evaluate_window,
)
from salvage.detect.thresholds import FROZEN, Thresholds
from salvage.ledger import Ledger
from salvage.sim.clock import IstCalendar


@dataclass
class OpenedIncident:
    incident_id: str
    segment_key: str
    opened_at: int
    scope: list[str]
    resegmented: int = 0


@dataclass
class DetectionReport:
    eval_start: int
    eval_end: int
    windows_evaluated: int
    opened: list[OpenedIncident] = field(default_factory=list)
    closed: list[tuple[str, int]] = field(default_factory=list)
    stats_written: int = 0

    @property
    def incidents_opened(self) -> int:
        return len(self.opened)


def detect(
    conn,
    *,
    eval_start: int,
    eval_end: int,
    thresholds: Thresholds = FROZEN,
    calendar: IstCalendar | None = None,
    persist: bool = True,
) -> DetectionReport:
    """Run the detector across [eval_start, eval_end).

    Baselines come from the trailing seven days before eval_start, so the evaluation day never
    contributes to its own baseline.
    """
    calendar = calendar or IstCalendar()
    baselines: Baselines = build_baselines(
        conn, baseline_end=eval_start, thresholds=thresholds, calendar=calendar
    )
    counters = build_counters(
        conn,
        start=eval_start - thresholds.window_seconds,
        end=eval_end,
        thresholds=thresholds,
    )

    ledger = Ledger(conn) if persist else None
    report = DetectionReport(eval_start=eval_start, eval_end=eval_end, windows_evaluated=0)

    # consecutive[key] counts windows in a row where conditions 1 to 3 held.
    consecutive: dict[str, int] = defaultdict(int)
    # recovered[incident_id] counts windows in a row where the key is back near baseline.
    recovered: dict[str, int] = defaultdict(int)
    open_by_key: dict[str, OpenedIncident] = {}
    pending_stats: list[WindowStat] = []

    for window_end in range(eval_start, eval_end + 1, thresholds.step_seconds):
        window_start = window_end - thresholds.window_seconds
        live, passing = evaluate_window(
            counters,
            baselines,
            window_start=window_start,
            window_end=window_end,
            calendar=calendar,
            thresholds=thresholds,
        )
        report.windows_evaluated += 1
        pending_stats.extend(live)

        passing_keys = {stat.segment_key for stat in passing}
        for key in list(consecutive):
            if key not in passing_keys:
                consecutive[key] = 0
        for key in passing_keys:
            consecutive[key] += 1

        # Condition 4: the four conditions must hold in two consecutive windows before anything
        # opens. Attribution then runs over every key that is firing right now, not only the ones
        # that have reached two windows. Those are different questions: condition 4 asks whether
        # this is real, attribution asks what shape it is. Running attribution over the confirmed
        # set alone attributed a fault to whichever key happened to cross first, which was
        # regularly a step key or a single UPI handle inside a merchant-wide outage.
        confirmed_keys = {
            key for key in passing_keys if consecutive[key] >= thresholds.consecutive_windows
        }
        if confirmed_keys:
            for group in incidents_mod.attribute(passing, thresholds):
                existing = _matching_incident(open_by_key, group.attributed)
                if existing is not None:
                    _resegment(
                        conn,
                        ledger,
                        existing,
                        group,
                        open_by_key=open_by_key,
                        persist=persist,
                        ts=window_end,
                        firing_keys=passing_keys,
                    )
                    continue
                if not (confirmed_keys & set(group.scope) or group.attributed in confirmed_keys):
                    # This group is firing but nothing in it has held for two windows yet.
                    continue
                at_risk = (
                    incidents_mod.at_risk_amount(
                        conn,
                        segment_key=group.attributed,
                        window_start=window_start,
                        evaluated_at=window_end,
                    )
                    if persist
                    else 0
                )
                incident_id = (
                    incidents_mod.open_incident(
                        conn,
                        segment_key=group.attributed,
                        opened_at=window_end,
                        scope=group.scope,
                        at_risk=at_risk,
                    )
                    if persist
                    else f"inc_dry_{group.attributed}_{window_end}"
                )
                opened = OpenedIncident(
                    incident_id=incident_id,
                    segment_key=group.attributed,
                    opened_at=window_end,
                    scope=group.scope,
                )
                report.opened.append(opened)
                open_by_key[group.attributed] = opened
                if ledger is not None:
                    ledger.append(
                        "detect.incident.opened",
                        "incident",
                        incident_id,
                        {
                            "segment_key": group.attributed,
                            "affected_scope": group.scope,
                            "window_start": window_start,
                            "window_end": window_end,
                            "at_risk_amount": at_risk,
                        },
                        ts=window_end,
                    )

        # Close: the incident's key and every key in its affected scope are back within 0.05 of
        # baseline for four consecutive windows. Architecture section 5 says "the key's rate";
        # the scope is included because an incident whose segment has recovered while a key in its
        # own recorded scope is still degraded has not recovered, and closing it there let the
        # same fault re-open as a second incident a few minutes later.
        live_by_key = {stat.segment_key: stat for stat in live}
        for key, opened in list(open_by_key.items()):
            judged = [
                live_by_key[scope_key]
                for scope_key in {key, *opened.scope}
                if scope_key in live_by_key
            ]
            if not judged:
                # Not enough volume anywhere in scope to judge. Neither recovery nor degradation.
                continue
            if all(
                stat.rate - stat.baseline_rate <= thresholds.close_within_of_baseline
                for stat in judged
            ):
                recovered[opened.incident_id] += 1
            else:
                recovered[opened.incident_id] = 0
            if recovered[opened.incident_id] >= thresholds.close_consecutive_windows:
                if persist:
                    incidents_mod.close_incident(conn, opened.incident_id, window_end)
                    if ledger is not None:
                        ledger.append(
                            "detect.incident.closed",
                            "incident",
                            opened.incident_id,
                            {"segment_key": key, "closed_at": window_end},
                            ts=window_end,
                        )
                report.closed.append((opened.incident_id, window_end))
                del open_by_key[key]

    if persist:
        report.stats_written = _persist_stats(conn, pending_stats)
    return report


def _matching_incident(
    open_by_key: dict[str, OpenedIncident], attributed: str
) -> OpenedIncident | None:
    """The open incident this firing group belongs to, if any.

    One fault produces one incident (Architecture section 5). A fault's shape changes as it
    spreads, so the key attribution lands on moves: an outage first seen on one UPI handle can
    turn out to be merchant-wide two minutes later. When that happens the existing incident is
    resegmented, not joined by a second one. Matching is by family (see
    salvage/detect/incidents.py); when several open incidents match, the earliest wins, because
    that is the one whose opened_at is the honest time of detection.
    """
    candidates = [
        incident
        for incident in open_by_key.values()
        if incidents_mod.same_family(incident.segment_key, attributed)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda incident: (incident.opened_at, incident.incident_id))


def _resegment(
    conn,
    ledger,
    incident: OpenedIncident,
    group,
    *,
    open_by_key: dict[str, OpenedIncident],
    persist: bool,
    ts: int,
    firing_keys: set[str],
) -> None:
    """Widen an open incident, keeping its identity and its opened_at.

    An incident's segment is only ever widened, never narrowed and never moved sideways. A fault
    can turn out to be broader than it first looked, which is a real thing to record; it does not
    turn into a different fault. Without this rule the attributed segment tracked whichever key
    happened to be firing in the last window, so a card BIN outage ended up labelled with the card
    issuer, and a gateway outage ended up labelled with a card authorisation step ten minutes
    after it had passed. The scope is always merged, whether or not the segment widens.
    """
    new_scope = sorted(set(incident.scope) | set(group.scope))
    # Widening also needs evidence that the fault really is one level up: at least two keys at the
    # incident's own level firing. See incidents.firing_siblings.
    widen = incidents_mod.is_ancestor(group.attributed, incident.segment_key) and (
        incidents_mod.firing_siblings(incident.segment_key, firing_keys) >= 2
    )
    if not widen:
        if new_scope != incident.scope:
            incident.scope = new_scope
            if persist:
                _update_incident_segment(
                    conn, incident.incident_id, incident.segment_key, new_scope
                )
        return
    old_key = incident.segment_key
    open_by_key.pop(old_key, None)
    incident.segment_key = group.attributed
    incident.scope = new_scope
    incident.resegmented += 1
    open_by_key[group.attributed] = incident
    if persist:
        _update_incident_segment(conn, incident.incident_id, group.attributed, new_scope)
        if ledger is not None:
            ledger.append(
                "detect.incident.resegmented",
                "incident",
                incident.incident_id,
                {"from": old_key, "to": group.attributed, "affected_scope": new_scope},
                ts=ts,
            )


def _update_incident_segment(conn, incident_id: str, segment_key: str, scope: list[str]) -> None:
    import json

    conn.execute(
        "UPDATE incidents SET segment_key = ?, affected_scope_json = ? WHERE id = ?",
        (segment_key, json.dumps(sorted(scope)), incident_id),
    )


def _persist_stats(conn, stats: list[WindowStat]) -> int:
    """Write the window statistics that were actually tested.

    Only windows where a key was live (at least min_attempts) are stored. Storing every key for
    every minute would be roughly 90,000 rows per simulated day, most of them describing a segment
    with two attempts in it, and would slow a calibration sweep down for no gain. The dashboard
    reads the most recent live window per key, which this keeps.
    """
    if not stats:
        return 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.executemany(
            "INSERT INTO segments_stats "
            "(segment_key, window_start, attempts, failures, baseline_rate, p_value) "
            "VALUES (:segment_key, :window_start, :attempts, :failures, :baseline_rate, :p_value) "
            "ON CONFLICT(segment_key, window_start) DO UPDATE SET "
            "attempts = excluded.attempts, failures = excluded.failures, "
            "baseline_rate = excluded.baseline_rate, p_value = excluded.p_value",
            [
                {
                    "segment_key": stat.segment_key,
                    "window_start": stat.window_start,
                    "attempts": stat.attempts,
                    "failures": stat.failures,
                    "baseline_rate": stat.baseline_rate,
                    "p_value": 1.0 if stat.p_value != stat.p_value else stat.p_value,
                }
                for stat in stats
            ],
        )
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
    return len(stats)
