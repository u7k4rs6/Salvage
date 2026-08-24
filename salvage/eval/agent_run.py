"""One full agent run over one scenario: simulate, detect, diagnose, plan, gate, act, settle.

Architecture section 13 does not name this file. It is the piece the M2 exit criteria call "a full
S1 run end to end in simulation", and it is what M3's evaluation runner will call once per
(scenario, seed, policy). Recorded in docs/BUILD_LOG.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from salvage import repo
from salvage.detect.run import detect
from salvage.eval.baselines import OrganicRecovery, measure_organic_recovery
from salvage.execute.scheduler import AgentRunner, RunStats, SimulatedLinkGateway
from salvage.sim.params import default_params, load
from salvage.sim.response import ResponseModel
from salvage.sim.runner import SimResult, run_scenario


@dataclass
class AgentRunResult:
    sim: SimResult
    stats: RunStats
    organic: OrganicRecovery
    incidents: list[dict[str, Any]]
    escalations: list[dict[str, Any]]

    @property
    def customer_contacts(self) -> int:
        return self.stats.messages_sent


def run_agent_scenario(
    conn,
    *,
    scenario: str,
    seed: int,
    variant: str = "peak",
    provider=None,
    params_path: Path | str | None = None,
    kill_switch: bool = False,
) -> AgentRunResult:
    """Simulate, detect, then run the agent over what happened."""
    params = load(params_path) if params_path else default_params()
    sim = run_scenario(conn, scenario=scenario, seed=seed, variant=variant, params_path=params_path)
    detect(
        conn,
        eval_start=sim.eval_day_start,
        eval_end=sim.eval_day_start + params.eval_days * 86400,
    )

    # Measured before the agent runs. Afterwards, an order the agent recovered is also "paid",
    # and B0 would silently absorb the agent's own recoveries into the floor it is meant to be
    # compared against.
    organic = measure_organic_recovery(
        conn,
        scenario=scenario,
        seed=seed,
        variant=variant,
        fault_windows=[(f.start_ts, f.end_ts) for f in sim.scheduled_faults],
    )

    runner = AgentRunner(
        conn,
        response=ResponseModel(params, seed),
        provider=provider,
        gateway=SimulatedLinkGateway(),
        kill_switch=kill_switch,
    )
    stats = runner.run(until=sim.sim_end)

    return AgentRunResult(
        sim=sim,
        stats=stats,
        organic=organic,
        incidents=repo.list_incidents(conn),
        escalations=[
            dict(row)
            for row in conn.execute("SELECT * FROM escalations ORDER BY created_at").fetchall()
        ],
    )
