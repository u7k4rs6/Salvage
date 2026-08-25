"""One policy over one simulated world.

Simulate, detect, run the policy, settle, measure. Called once per (scenario, seed, policy) by the
evaluation runner in salvage/eval/run.py.

Two things here make the comparison honest, and both are asserted by tests rather than assumed:

  The world is the same for every policy. The simulation is deterministic given a seed, no policy
  writes a payment attempt, and the pre-intervention attempt stream digest is therefore identical
  across all four arms. `stream_digest` is returned on every result so the runner can print them
  side by side.

  The measured population is the same for every policy. Metrics are computed over
  `eval.baselines.eligible_orders`, every order whose first attempt failed inside the evaluation
  window, which is a property of the world and not of what any policy did.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from salvage import repo
from salvage.detect.run import detect
from salvage.eval.baselines import PolicyProfile, get_policy
from salvage.eval.metrics import RunMetrics, measure_run
from salvage.execute.scheduler import AgentRunner, RunStats, SimulatedLinkGateway
from salvage.sim.params import default_params, load
from salvage.sim.response import ResponseModel
from salvage.sim.runner import SimResult, run_scenario


class _Unset:
    """Distinguishes "the caller said nothing" from "the caller said never".

    None is a meaningful value here: it is `never`. A sweep that passes None must get no repair,
    and a caller that passes nothing must get whatever the parameter file says, so the two cases
    cannot share a sentinel.
    """


UNSET = _Unset()


@dataclass
class PolicyRunResult:
    sim: SimResult
    profile: PolicyProfile
    stats: RunStats
    metrics: RunMetrics
    incidents: list[dict[str, Any]]
    escalations: list[dict[str, Any]]

    @property
    def customer_contacts(self) -> int:
        return self.stats.messages_sent

    @property
    def stream_digest(self) -> str:
        return self.sim.stream_digest


def run_policy_scenario(
    conn,
    *,
    scenario: str,
    seed: int,
    policy: str = "agent",
    variant: str = "peak",
    provider=None,
    params_path: Path | str | None = None,
    kill_switch: bool = False,
    escalation_fix_minutes: int | None | _Unset = UNSET,
) -> PolicyRunResult:
    """Simulate, detect, run one policy, settle, measure.

    `escalation_fix_minutes` defaults to whatever sim/params.yaml says, which is `never`. It is
    an argument as well as a parameter so the sweep can vary it without rewriting the file it is
    supposed to be measuring.
    """
    profile = get_policy(policy)
    params = load(params_path) if params_path else default_params()
    fix_minutes = (
        params.escalation_fix_minutes
        if isinstance(escalation_fix_minutes, _Unset)
        else escalation_fix_minutes
    )

    sim = run_scenario(conn, scenario=scenario, seed=seed, variant=variant, params_path=params_path)
    window_start = sim.eval_day_start
    window_end = sim.eval_day_start + params.eval_days * 86400

    # The detector runs for every policy, including B0. Detection is not part of what separates
    # the arms, and running it everywhere means false alarms and time to detect are measured once
    # per world rather than once per agent run.
    detect(conn, eval_start=window_start, eval_end=window_end)

    runner = AgentRunner(
        conn,
        response=ResponseModel(params, seed),
        provider=provider if profile.diagnoses else None,
        gateway=SimulatedLinkGateway(),
        kill_switch=kill_switch,
        profile=profile,
        seed=seed,
        world_faults=[
            {"start": f.start_ts, "end": f.end_ts, "selector": dict(f.fault.selector)}
            for f in sim.scheduled_faults
        ],
        escalation_fix_minutes=fix_minutes,
    )
    stats = runner.run(until=sim.sim_end, window_start=window_start, window_end=window_end)

    from salvage.eval.baselines import FaultWindow

    fault_windows = [
        FaultWindow(start=f.start_ts, end=f.end_ts, selector=dict(f.fault.selector))
        for f in sim.scheduled_faults
    ]
    metrics = measure_run(
        conn,
        scenario=scenario,
        seed=seed,
        policy=policy,
        variant=variant,
        window_start=window_start,
        window_end=window_end,
        fault_windows=fault_windows,
    )
    incidents = repo.list_incidents(conn)
    escalations = [
        dict(row)
        for row in conn.execute("SELECT * FROM escalations ORDER BY created_at").fetchall()
    ]

    metrics.messages_sent = stats.messages_sent
    metrics.links_created = stats.links_created
    metrics.opt_outs = stats.opt_outs
    metrics.escalations = len(escalations)
    metrics.actions_refused = stats.actions_refused
    metrics.stream_digest = sim.stream_digest
    # An incident opened by the detector counts for every policy; a synthetic baseline incident
    # does not, because no detector opened it.
    metrics.incidents = sum(
        1 for incident in incidents if not str(incident["id"]).endswith("_baseline")
    )
    metrics.time_to_detect_minutes = _time_to_detect(
        incidents, [(w.start, w.end) for w in fault_windows]
    )
    metrics.policy_violations = count_policy_violations(conn)

    return PolicyRunResult(
        sim=sim,
        profile=profile,
        stats=stats,
        metrics=metrics,
        incidents=incidents,
        escalations=escalations,
    )


def _time_to_detect(
    incidents: list[dict[str, Any]], fault_windows: list[tuple[int, int]]
) -> float | None:
    if not fault_windows:
        return None
    start = fault_windows[0][0]
    opened = [
        int(incident["opened_at"])
        for incident in incidents
        if int(incident["opened_at"]) >= start and not str(incident["id"]).endswith("_baseline")
    ]
    return (min(opened) - start) / 60.0 if opened else None


# ---------------------------------------------------------------------------
# Policy violations
# ---------------------------------------------------------------------------

# docs/01_PRD.md section 11: "Policy violations: any action that breaks a section 9 rule; target
# zero, across all runs and the harness." The policy engine is supposed to make these impossible,
# so this counts them from the recorded state rather than from the gates: a violation that only
# the gate log denies would be exactly the kind of thing worth catching.
_VIOLATION_QUERIES: dict[str, str] = {
    "message_without_consent": """
        SELECT COUNT(*) FROM customer_comms c JOIN customers u ON u.id = c.customer_id
        WHERE u.consent = 0
    """,
    "message_after_opt_out": """
        SELECT COUNT(*) FROM customer_comms c JOIN customers u ON u.id = c.customer_id
        WHERE u.opted_out_at IS NOT NULL AND c.sent_at > u.opted_out_at
    """,
    "over_incident_nudge_cap": """
        SELECT COUNT(*) FROM (
            SELECT customer_id, incident_id, COUNT(*) n FROM customer_comms
            WHERE incident_id IS NOT NULL GROUP BY 1, 2 HAVING n > 2
        )
    """,
    "over_seven_day_cap": """
        SELECT COUNT(*) FROM (
            SELECT c.id FROM customer_comms c
            WHERE (SELECT COUNT(*) FROM customer_comms o
                   WHERE o.customer_id = c.customer_id
                     AND o.sent_at <= c.sent_at
                     AND o.sent_at > c.sent_at - 604800) > 3
        )
    """,
    "two_open_links_for_one_order": """
        SELECT COUNT(*) FROM (
            SELECT order_id, COUNT(*) n FROM recovery_cases
            WHERE link_id IS NOT NULL GROUP BY 1 HAVING n > 1
        )
    """,
    "link_for_a_paid_order": """
        SELECT COUNT(*) FROM recovery_cases c JOIN orders o ON o.id = c.order_id
        WHERE c.link_id IS NOT NULL AND o.paid_at IS NOT NULL AND o.paid_at < c.updated_at
          AND c.outcome NOT IN ('PAID_ELSEWHERE', 'RECOVERED')
    """,
    "message_past_the_order_ttl": """
        SELECT COUNT(*) FROM customer_comms c JOIN recovery_cases r ON r.id = c.case_id
        WHERE c.sent_at > r.ttl_at
    """,
}


def count_policy_violations(conn, calendar=None) -> int:
    """Count of section 9 violations visible in the recorded state. Target is zero."""
    return sum(violation_breakdown(conn, calendar).values())


def violation_breakdown(conn, calendar=None) -> dict[str, int]:
    from salvage.decide.policy import QUIET_HOURS_END, QUIET_HOURS_START
    from salvage.sim.clock import IstCalendar

    calendar = calendar or IstCalendar()
    counts = {
        name: int(conn.execute(query).fetchone()[0]) for name, query in _VIOLATION_QUERIES.items()
    }
    # Quiet hours need IST arithmetic, so this one is a scan rather than a query.
    quiet = 0
    for row in conn.execute("SELECT sent_at FROM customer_comms"):
        if calendar.is_quiet_hours(int(row["sent_at"]), QUIET_HOURS_START, QUIET_HOURS_END):
            quiet += 1
    counts["message_inside_quiet_hours"] = quiet
    return counts


# Kept so existing callers and tests keep working while the runner moves to run_policy_scenario.
def run_agent_scenario(conn, **kwargs) -> PolicyRunResult:
    kwargs.setdefault("policy", "agent")
    return run_policy_scenario(conn, **kwargs)
