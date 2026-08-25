"""The agent loop: diagnose, plan, gate, act, settle.

docs/02_TECHNICAL_ARCHITECTURE.md section 8. The scheduler "advances deferred cases, enforces
TTLs, evaluates the circuit breaker, and releases quiet-hour queues", driven by the sim clock in
simulation and by wall time when live.

How this works against a simulated run, and why it is honest.

The simulator produces the world first: every attempt, every organic retry, every organic payment.
The agent then runs over that world. An order the agent recovers with a link would not have made
its later organic retries in reality, and it does not need to: an order is paid once, and the
attribution goes to whichever happened first. That is what the per-order random streams in
salvage/sim/rng.py are for. The agent and every baseline see the same customers making the same
organic decisions, and differ only in what they did about them.

The policy engine runs before every individual action, never once per plan. Nothing in this module
sends anything anywhere: the channel is simulated and the link gateway is an interface with a
simulated implementation and a real Razorpay one.
"""

from __future__ import annotations

import contextlib
import heapq
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Protocol

from salvage import repo, taxonomy
from salvage.decide import policy as policy_mod
from salvage.decide.menu import ActionType, Scope
from salvage.decide.planner import EligibilityCounts, Plan, plan_incident, plan_json
from salvage.decide.policy import ORDER_TTL_SECONDS, Decision
from salvage.detect.segments import ALL_KEY, parse_key
from salvage.diagnose.reconcile import diagnose_incident, persist_diagnosis
from salvage.eval.baselines import AGENT, EligibleOrder, PolicyProfile, eligible_orders
from salvage.execute import channels
from salvage.execute.workflow import (
    CaseState,
    advance,
    is_terminal,
    outcome_for,
    terminal_target_for,
)
from salvage.ledger import Ledger
from salvage.sim.clock import IstCalendar
from salvage.sim.response import ResponseModel
from salvage.sim.rng import order_stream

# How long after a nudge a customer who is going to pay actually pays. Drawn per order so it is
# deterministic; the bounds are here rather than params.yaml because they describe the agent's
# accounting window, not customer behaviour, and moving them cannot change any recovery total.
LINK_PAY_MIN_SECONDS = 5 * 60
LINK_PAY_MAX_SECONDS = 6 * 3600

# A second nudge is offered this long after the first, if the caps and the policy still allow it.
SECOND_NUDGE_DELAY_SECONDS = 6 * 3600

# How often the agent re-sweeps an open incident for newly failed orders, and how many sweeps it
# will do. Eight sweeps at 15 minutes covers two hours, which is longer than the longest fault in
# sim/params.yaml (S4, three hours, is covered until the incident closes instead). A sweep stops
# early once the incident has closed.
SWEEP_INTERVAL_SECONDS = 15 * 60
MAX_INCIDENT_SWEEPS = 12

# A steered customer completes in the same session, so the payment lands minutes after the
# failure rather than hours. This is not a tuning knob: it only decides which route wins the
# attribution when a steer and an organic retry would both have recovered the same order, and the
# steer genuinely happened first.
STEER_PAY_SECONDS = 4 * 60


class LinkGateway(Protocol):
    """Creating and cancelling a payment link. Two implementations, one interface."""

    def create_link(
        self,
        *,
        case_id: str,
        amount: int,
        expire_by: int,
        description: str,
        checkout_display: dict[str, Any] | None,
    ) -> dict[str, Any]: ...

    def cancel_link(self, link_id: str) -> None: ...


@dataclass
class SimulatedLinkGateway:
    """Links in simulation. No network, no Razorpay account, no money.

    The link ids look like Razorpay's (plink_...) so nothing downstream can tell the difference by
    shape, and the executor's code path is identical to the real one.
    """

    created: list[dict[str, Any]] = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)

    def create_link(
        self,
        *,
        case_id: str,
        amount: int,
        expire_by: int,
        description: str,
        checkout_display: dict[str, Any] | None,
    ) -> dict[str, Any]:
        link_id = f"plink_sim{len(self.created):012d}"
        link = {
            "id": link_id,
            "reference_id": case_id,
            "amount": amount,
            "currency": "INR",
            "status": "created",
            "expire_by": expire_by,
            "short_url": f"https://rzp.io/i/sim{len(self.created):08d}",
            "description": description,
            "notify": {"sms": False, "email": False},
            "options": (
                {"checkout": {"config": {"display": checkout_display}}} if checkout_display else {}
            ),
        }
        self.created.append(link)
        return link

    def cancel_link(self, link_id: str) -> None:
        self.cancelled.append(link_id)


@dataclass
class RunStats:
    incidents: int = 0
    diagnosed: int = 0
    escalations: int = 0
    actions_proposed: int = 0
    actions_executed: int = 0
    actions_refused: int = 0
    actions_deferred: int = 0
    actions_queued: int = 0
    links_created: int = 0
    messages_sent: int = 0
    messages_rejected: int = 0
    opt_outs: int = 0
    recovered_cases: int = 0
    recovered_amount: int = 0
    cases: int = 0
    steer_opportunities: int = 0
    steer_recoveries: int = 0
    steer_amount: int = 0
    organic_recoveries: int = 0
    fixes_applied: int = 0
    fix_recoveries: int = 0

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(order=True)
class _Timer:
    at: int
    sequence: int
    kind: str = field(compare=False)
    case_id: str = field(compare=False)
    incident_id: str = field(compare=False)
    payload: dict[str, Any] = field(compare=False, default_factory=dict)


class AgentRunner:
    """One agent run over one simulated world."""

    def __init__(
        self,
        conn,
        *,
        response: ResponseModel,
        provider=None,
        gateway: LinkGateway | None = None,
        kill_switch: bool = False,
        calendar: IstCalendar | None = None,
        profile: PolicyProfile = AGENT,
        seed: int = 0,
        world_faults: list[dict[str, Any]] | None = None,
        escalation_fix_minutes: int | None = None,
    ) -> None:
        self._conn = conn
        self._response = response
        self._provider = provider
        self._gateway = gateway or SimulatedLinkGateway()
        self._kill_switch = kill_switch
        self._profile = profile
        self._seed = int(seed)
        # World state, not agent state. Whether a customer's rail is broken at the moment a nudge
        # reaches them is a fact about the world, and the customer response model is part of the
        # simulator, so it is entitled to know it. No policy code path reads this: it is used only
        # inside _apply_customer_response, and the alternative was reading it off the detector's
        # incidents, which made a baseline's outcome depend on whether the agent had detected
        # anything. Each entry is {"start", "end", "selector"}.
        self._world_faults = list(world_faults or [])
        # Escalation to fix, from sim/params.yaml. None means never, which is the pre-M5
        # behaviour: the agent files an escalation and the world carries on failing. Also world
        # state rather than agent state, and read in exactly one place, _repair_world.
        self._escalation_fix_minutes = escalation_fix_minutes
        self._repaired_incidents: set[str] = set()
        self._calendar = calendar or IstCalendar()
        self._ledger = Ledger(conn)
        self._timers: list[_Timer] = []
        self._sequence = 0
        self._action_serial = 0
        self.stats = RunStats()

    # -- entry point -------------------------------------------------------

    def run(self, *, until: int, window_start: int = 0, window_end: int | None = None) -> RunStats:
        """Run this policy over the world, then settle every timer up to `until`.

        The agent works from incidents: it diagnoses, plans, and acts on the affected population.
        The baselines have no incidents and no cause; they work from the eligible order set
        directly, which is the same set the metrics are computed over. Both then run through the
        same policy engine, the same state machine and the same channel.
        """
        # The organic outcome is snapshotted before anything acts. At this point every paid order
        # was paid by a customer coming back on their own, because no policy has run yet. A link
        # or a steer that lands earlier will take the order from it during settlement.
        self._record_organic_routes()

        if self._profile.diagnoses:
            for incident in repo.list_incidents(self._conn):
                self._handle_incident(incident)
        elif self._profile.nudge_offsets:
            self._run_fixed_schedule(window_start, window_end or until)
        self._settle(until)
        return self.stats

    def _run_fixed_schedule(self, window_start: int, window_end: int) -> None:
        """B1 and B2: a case per eligible order, nudged at fixed offsets after its failure.

        No incident, no cause, no diagnosis. Every other gate the agent obeys still runs, which is
        what Architecture section 10 means by sharing the executor and the policy engine.
        """
        incident = self._synthetic_incident(window_start)
        for order in eligible_orders(self._conn, start=window_start, end=window_end):
            # The case carries the synthetic incident id. Without it the circuit breaker counted
            # sends (which are recorded against the incident) against recoveries (which are
            # recorded against cases), found zero conversions no matter how many there were, and
            # tripped a few hours into every baseline run.
            case = self._open_case_for(order, incident_id=str(incident["id"]), now=order.failed_at)
            if case is None:
                continue
            for offset in self._profile.nudge_offsets:
                self._schedule(
                    order.failed_at + offset,
                    "fixed_nudge",
                    case["id"],
                    incident["id"],
                    {"case_id": case["id"]},
                )

    def _synthetic_incident(self, now: int) -> dict[str, Any]:
        """The incident row a baseline acts under.

        A baseline does not detect anything, but the executor and the policy engine are written
        against an incident, and inventing one here rather than threading `incident | None`
        through every call site keeps the two paths identical everywhere it matters. Its cause is
        never read, because a baseline's context sets apply_matrix False.
        """
        incident_id = f"inc_{self._profile.name}_baseline"
        if repo.get_incident(self._conn, incident_id) is None:
            repo.insert_incident(
                self._conn,
                {
                    "id": incident_id,
                    "segment_key": ALL_KEY,
                    "opened_at": now,
                    "closed_at": None,
                    "at_risk_amount": 0,
                    "rules_cause": None,
                    "llm_cause": None,
                    "root_cause": None,
                    "confidence": None,
                    "plan_json": None,
                    "status": "open",
                    "affected_scope_json": "[]",
                },
            )
        return repo.get_incident(self._conn, incident_id)

    def _open_case_for(
        self, order: EligibleOrder, *, incident_id: str | None, now: int
    ) -> dict[str, Any] | None:
        if repo.get_case_for_order(self._conn, order.order_id) is not None:
            return None
        existing = repo.get_order(self._conn, order.order_id) or {}
        if _paid_by(existing, now):
            return None
        case = {
            "id": f"case_{order.order_id}",
            "order_id": order.order_id,
            "customer_id": order.customer_id,
            "incident_id": incident_id,
            "state": CaseState.DETECTED.value,
            "attempts": 0,
            "link_id": None,
            "link_url": None,
            "next_action_at": None,
            "ttl_at": int(existing.get("created_at") or order.failed_at) + ORDER_TTL_SECONDS,
            "outcome": None,
            "updated_at": now,
        }
        repo.insert_case(self._conn, case)
        self.stats.cases += 1
        return case

    def _record_organic_routes(self) -> None:
        """Snapshot the organic outcome before any policy acts.

        Every order paid at this moment was paid by a customer who came back unprompted, because
        the simulator has finished and nothing else has run. Recorded with its own timestamp, so a
        link or a steer that lands earlier takes the order later on the paid_at rule.
        """
        rows = self._conn.execute(
            "SELECT id, paid_at FROM v_orders WHERE status = 'paid' AND paid_at IS NOT NULL"
        ).fetchall()
        for row in rows:
            if repo.record_recovery_route(
                self._conn,
                order_id=str(row["id"]),
                route="organic",
                paid_at=int(row["paid_at"]),
                policy=self._profile.name,
            ):
                self.stats.organic_recoveries += 1

    # -- incident ----------------------------------------------------------

    def _handle_incident(self, incident: dict[str, Any]) -> None:
        self.stats.incidents += 1
        incident_id = str(incident["id"])
        now = int(incident["opened_at"])

        diagnosis, packet = diagnose_incident(self._conn, incident, provider=self._provider)
        persist_diagnosis(self._conn, diagnosis, packet, self._ledger)
        self.stats.diagnosed += 1
        incident = repo.get_incident(self._conn, incident_id) or incident

        cases = self._open_cases(incident, now)
        counts = self._eligibility_counts(cases, incident_id, now)
        # "Recovered" means recovered by now, not recovered at some point in the run. The agent
        # runs over a completed simulation, so an incident row always has a closed_at; reading it
        # without comparing against the current time told the planner the fault was already over
        # while it was still failing payments.
        segment_recovered = self._segment_recovered(incident, now)

        plan, plan_error = plan_incident(
            self._provider,
            incident_id=incident_id,
            segment_key=str(incident["segment_key"]),
            cause=str(incident.get("root_cause") or "unknown"),
            confidence=float(incident.get("confidence") or 0.0),
            counts=counts,
            segment_recovered=segment_recovered,
            value_threshold_paise=policy_mod.VALUE_THRESHOLD_PAISE,
            conn=self._conn,
        )
        self._conn.execute(
            "UPDATE incidents SET plan_json = ? WHERE id = ?", (plan_json(plan), incident_id)
        )
        self._ledger.append(
            "decide.plan",
            "incident",
            incident_id,
            {
                "plan": json.loads(plan.model_dump_json()),
                "planner_error": plan_error,
                "eligibility": json.loads(counts.model_dump_json()),
            },
            ts=now,
        )

        if diagnosis.escalate:
            self._escalate(
                incident_id,
                reason=diagnosis.escalation_reason or "low confidence",
                packet=packet,
                proposed=json.loads(plan.model_dump_json()),
                now=now,
            )

        self._apply_plan(incident, plan, cases, now)

        # An incident is not a moment. The detection window holds the failures that triggered it,
        # but the fault keeps failing payments for as long as it lasts, and those orders are the
        # ones a recovery agent exists for. Sweep every window until the incident closes, opening
        # cases for newly failed orders and applying the same plan to them under the same gates.
        for offset in range(1, MAX_INCIDENT_SWEEPS + 1):
            self._schedule(
                now + offset * SWEEP_INTERVAL_SECONDS,
                "sweep",
                "",
                incident_id,
                {"plan": json.loads(plan.model_dump_json())},
            )

    def _open_cases(self, incident: dict[str, Any], now: int) -> list[dict[str, Any]]:
        """One recovery case per affected order that is still unpaid.

        Affected means the order's failed attempt lies inside the incident window and inside the
        incident's segment. Reads the v_ views, so no ground truth.
        """
        segment_key = str(incident["segment_key"])
        window_start = now - 15 * 60
        method, dimension, value = parse_key(segment_key)
        conditions = ["a.status = 'failed'", "a.created_at >= ?", "a.created_at < ?"]
        args: list[Any] = [window_start, now]
        if segment_key != ALL_KEY:
            conditions.append("a.method = ?")
            args.append(method)
        column = {
            "upi_handle": "a.upi_handle",
            "card_bin6": "a.card_bin",
            "card_issuer": "a.card_issuer",
            "card_network": "a.card_network",
            "nb_bank": "a.nb_bank",
            "error_step": "a.error_step",
        }.get(dimension or "")
        if column:
            conditions.append(f"{column} = ?")
            args.append(value)

        rows = self._conn.execute(
            "SELECT DISTINCT a.order_id, a.customer_id, o.amount, o.created_at, o.status "
            "FROM v_payment_attempts a JOIN v_orders o ON o.id = a.order_id "
            "WHERE " + " AND ".join(conditions),
            tuple(args),
        ).fetchall()

        cases: list[dict[str, Any]] = []
        for row in rows:
            if row["status"] == "paid":
                continue
            if repo.get_case_for_order(self._conn, str(row["order_id"])) is not None:
                continue
            case_id = f"case_{row['order_id']}"
            case = {
                "id": case_id,
                "order_id": str(row["order_id"]),
                "customer_id": str(row["customer_id"]),
                "incident_id": str(incident["id"]),
                "state": CaseState.DETECTED.value,
                "attempts": 0,
                "link_id": None,
                "link_url": None,
                "next_action_at": None,
                "ttl_at": int(row["created_at"]) + ORDER_TTL_SECONDS,
                "outcome": None,
                "updated_at": now,
            }
            repo.insert_case(self._conn, case)
            cases.append(case)
            self.stats.cases += 1
        return cases

    def _eligibility_counts(
        self, cases: list[dict[str, Any]], incident_id: str, now: int
    ) -> EligibilityCounts:
        """Counts only. This is everything the planner learns about the customers."""
        counts = EligibilityCounts(affected_orders=len(cases), unpaid_orders=len(cases))
        for case in cases:
            customer = repo.get_customer(self._conn, case["customer_id"]) or {}
            order = repo.get_order(self._conn, case["order_id"]) or {}
            if customer.get("opted_out_at") is not None:
                counts.opted_out += 1
                continue
            if customer.get("consent"):
                counts.consented += 1
                if customer.get("alt_method"):
                    counts.consented_with_alternate += 1
            last = self._conn.execute(
                "SELECT error_reason FROM v_payment_attempts WHERE order_id = ? "
                "ORDER BY created_at DESC, id DESC LIMIT 1",
                (case["order_id"],),
            ).fetchone()
            if last and taxonomy.is_hard_decline(last["error_reason"]):
                counts.hard_declined += 1
            if int(order.get("amount") or 0) >= policy_mod.VALUE_THRESHOLD_PAISE:
                counts.above_value_threshold += 1
        return counts

    # -- plan application --------------------------------------------------

    def _apply_plan(
        self, incident: dict[str, Any], plan: Plan, cases: list[dict[str, Any]], now: int
    ) -> None:
        incident_id = str(incident["id"])
        for planned in plan.actions:
            self.stats.actions_proposed += 1
            if planned.type in (ActionType.ESCALATE_HUMAN, ActionType.NO_ACTION):
                if self._incident_level_done(incident_id, planned.type):
                    continue
                self._record_action(
                    incident_id, planned.type, None, planned.params, "executed", [], now
                )
                if planned.type == ActionType.ESCALATE_HUMAN:
                    self._escalate(
                        incident_id,
                        reason=str(planned.params.get("reason", "planner escalation")),
                        packet=None,
                        proposed=json.loads(planned.model_dump_json()),
                        now=now,
                    )
                self.stats.actions_executed += 1
                continue

            if planned.type == ActionType.STEER_METHOD:
                if self._incident_level_done(incident_id, planned.type):
                    continue
                self._apply_steer(incident, planned, now)
                continue

            targets = self._scope_targets(cases, planned.scope)
            for case in targets:
                self._apply_case_action(incident, planned.type, planned.params, case, now)

    @staticmethod
    def _segment_recovered(incident: dict[str, Any], now: int) -> bool:
        closed_at = incident.get("closed_at")
        return closed_at is not None and now >= int(closed_at)

    def _incident_level_done(self, incident_id: str, action_type: ActionType) -> bool:
        """Whether an incident-level action has already run for this incident.

        A sweep re-applies the plan to new cases. It must not re-hide the same methods or open the
        same escalation every fifteen minutes.
        """
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM actions WHERE incident_id = ? AND type = ? "
            "AND case_id IS NULL",
            (incident_id, action_type.value),
        ).fetchone()
        return bool(row["n"])

    def _scope_targets(self, cases: list[dict[str, Any]], scope: Scope) -> list[dict[str, Any]]:
        if scope == Scope.CONSENTED_WITH_ALTERNATE:
            keep = []
            for case in cases:
                customer = repo.get_customer(self._conn, case["customer_id"]) or {}
                if customer.get("consent") and customer.get("alt_method"):
                    keep.append(case)
            return keep
        return list(cases)

    def _apply_steer(self, incident: dict[str, Any], planned, now: int) -> None:
        incident_id = str(incident["id"])
        context = policy_mod.build_context(
            self._conn,
            action_type=ActionType.STEER_METHOD,
            incident=incident,
            now=now,
            kill_switch=self._kill_switch,
            apply_matrix=self._profile.applies_matrix,
            apply_defer_while_degraded=self._profile.defers_while_degraded,
            policy_name=self._profile.name,
        )
        verdict = policy_mod.evaluate(context, self._calendar)
        if not verdict.allowed:
            self._refuse(incident_id, ActionType.STEER_METHOD, None, planned.params, verdict, now)
            return

        params = planned.validated_params()
        hint = {
            "segment_key": str(incident["segment_key"]),
            "hide_json": json.dumps([m.value for m in params.hide_methods]),
            "sequence_json": json.dumps([m.value for m in params.prefer_methods]),
            "active_from": now,
            "active_to": None,
            "incident_id": incident_id,
        }
        # A second hint for the same segment in the same second is a no-op, not an error: the
        # primary key is (segment_key, active_from).
        with contextlib.suppress(sqlite3.IntegrityError):
            repo.insert_checkout_hint(self._conn, hint)
        self._record_action(
            incident_id,
            ActionType.STEER_METHOD,
            None,
            planned.params,
            "executed",
            verdict.gates_json(),
            now,
        )
        self.stats.actions_executed += 1
        self._schedule(now, "steer_sweep", "", incident_id, {"hint_from": now})

    def _apply_case_action(
        self,
        incident: dict[str, Any],
        action_type: ActionType,
        params: dict[str, Any],
        case: dict[str, Any],
        now: int,
    ) -> None:
        incident_id = str(incident["id"])
        case = repo.get_case(self._conn, case["id"]) or case
        if is_terminal(case["state"]):
            return

        segment_degraded = not self._segment_recovered(incident, now)
        context = policy_mod.build_context(
            self._conn,
            action_type=action_type,
            incident=incident,
            now=now,
            case=case,
            segment_degraded=segment_degraded,
            segment_recovered=not segment_degraded,
            kill_switch=self._kill_switch,
            apply_matrix=self._profile.applies_matrix,
            apply_defer_while_degraded=self._profile.defers_while_degraded,
            policy_name=self._profile.name,
        )
        verdict = policy_mod.evaluate(context, self._calendar)

        if verdict.decision == Decision.DEFER:
            self._ensure_eligible(case, now)
            if CaseState(case["state"]) == CaseState.ELIGIBLE:
                self._to_state(case, CaseState.DEFERRED, now)
            release_at = int(incident.get("closed_at") or now + 3600)
            self._schedule(release_at, "release_deferred", case["id"], incident_id, params)
            self._record_action(
                incident_id, action_type, case["id"], params, "deferred", verdict.gates_json(), now
            )
            self.stats.actions_deferred += 1
            return

        if verdict.decision == Decision.QUEUE:
            self._ensure_eligible(case, now)
            if CaseState(case["state"]) == CaseState.ELIGIBLE:
                self._to_state(case, CaseState.DEFERRED, now)
            self._schedule(
                int(verdict.scheduled_for or now), "release_quiet", case["id"], incident_id, params
            )
            self._record_action(
                incident_id, action_type, case["id"], params, "queued", verdict.gates_json(), now
            )
            self.stats.actions_queued += 1
            return

        if not verdict.allowed:
            self._refuse(incident_id, action_type, case["id"], params, verdict, now)
            self._close_refused(case, matrix=policy_mod.refused_for_matrix(verdict), now=now)
            return

        if action_type == ActionType.DEFER_UNTIL_RECOVERED:
            self._ensure_eligible(case, now)
            if CaseState(case["state"]) == CaseState.ELIGIBLE:
                self._to_state(case, CaseState.DEFERRED, now)
            release_at = int(incident.get("closed_at") or now + 3600)
            self._schedule(release_at, "release_deferred", case["id"], incident_id, params)
            self._record_action(
                incident_id, action_type, case["id"], params, "executed", verdict.gates_json(), now
            )
            self.stats.actions_executed += 1
            return

        self._send_recovery_link(incident, case, params, verdict, now)

    # -- the one action that touches the world -----------------------------

    def _send_recovery_link(
        self, incident: dict[str, Any], case: dict[str, Any], params, verdict, now: int
    ) -> None:
        incident_id = str(incident["id"])
        order = repo.get_order(self._conn, case["order_id"]) or {}
        customer = repo.get_customer(self._conn, case["customer_id"]) or {}
        # The amount comes from the order row. There is no amount in `params` to read.
        amount = int(order["amount"])
        expire_by = int(case["ttl_at"])

        # One open link per order (docs/01_PRD.md section 9). A second nudge reuses the link the
        # first one created rather than making another; the cap is on links, not on messages, and
        # the message cap is the separate two-per-incident rule.
        if case.get("link_id"):
            link = {"id": case["link_id"], "short_url": case.get("link_url")}
        else:
            hint = self._active_hint(incident_id)
            link = self._gateway.create_link(
                case_id=str(case["id"]),
                amount=amount,
                expire_by=expire_by,
                description=f"Recovery link for order {case['order_id']}",
                checkout_display=hint,
            )
            self._conn.execute(
                "UPDATE recovery_cases SET link_id = ?, link_url = ? WHERE id = ?",
                (link["id"], link.get("short_url"), case["id"]),
            )
            # Keep the in-memory case in step with the row. Everything downstream in this call,
            # including the cancel path when the order turns out to be paid, reads this dict.
            case["link_id"] = link["id"]
            case["link_url"] = link.get("short_url")
            self.stats.links_created += 1

        # Re-read the order between creating the link and sending the message. The gate checked it
        # a moment ago, but creating a Payment Link is a network call and the customer can pay by
        # another route while it is in flight. docs/03_SECURITY_AND_ACCESS.md section 6 says a
        # customer who paid in the meantime is never nudged, and "in the meantime" includes this
        # window. Found by tests/fault_injection/test_razorpay_faults.py.
        order_now = repo.get_order(self._conn, str(case["order_id"])) or {}
        if _paid_by(order_now, now):
            self._close_paid_elsewhere(case, now)
            self._record_action(
                incident_id,
                ActionType.SEND_RECOVERY_LINK,
                str(case["id"]),
                {"case_id": str(case["id"])},
                "refused",
                verdict.gates_json()
                + [
                    {
                        "rule": "case.order_paid_during_link_creation",
                        "passed": False,
                        "detail": "the order was paid while the link was being created",
                    }
                ],
                now,
            )
            self.stats.actions_refused += 1
            return

        self._walk_to_link(case, now)

        # Only a steering policy names an alternate method. B1 and B2 send a plain link, which
        # is what they are: docs/01_PRD.md section 12 says the baselines differ from the agent
        # exactly in "cause-aware timing and method steering", so handing them the steer inside the
        # message would have rigged the comparison in the baselines' favour.
        alternate = self._alternate_offer(incident, customer, now)
        message = channels.render(
            template_id="recovery_link_v1",
            locale=str(customer.get("locale") or "en"),
            order_ref=str(case["order_id"])[-10:],
            link_url=str(link.get("short_url") or ""),
            expiry_text=self._expiry_text(expire_by),
            alternate_method=alternate,
        )
        if not message.validation.ok:
            # A message that fails the validator is never sent. The link stays, so the customer
            # can still pay if they find it, but Salvage does not push a message it cannot vouch
            # for (Architecture section 8).
            self.stats.messages_rejected += 1
            self._record_action(
                incident_id,
                ActionType.SEND_RECOVERY_LINK,
                case["id"],
                dict(params) if isinstance(params, dict) else {},
                "failed",
                verdict.gates_json()
                + [
                    {
                        "rule": "channel.template_validator",
                        "passed": False,
                        "detail": str(message.validation),
                    }
                ],
                now,
            )
            return

        nudge_number = int(case["attempts"]) + 1
        comm_id = f"comm_{case['id']}_{nudge_number}"
        repo.insert_comm(
            self._conn,
            channels.comm_row(
                comm_id=comm_id,
                customer_id=str(case["customer_id"]),
                case_id=str(case["id"]),
                incident_id=incident_id,
                message=message,
                sent_at=now,
            ),
        )
        self._conn.execute(
            "UPDATE recovery_cases SET attempts = ? WHERE id = ?", (nudge_number, case["id"])
        )
        self._to_state(case, CaseState.NUDGED, now)
        self._to_state(case, CaseState.WAITING, now)
        self.stats.messages_sent += 1
        self._record_action(
            incident_id,
            ActionType.SEND_RECOVERY_LINK,
            case["id"],
            {"case_id": str(case["id"])},
            "executed",
            verdict.gates_json(),
            now,
        )
        self.stats.actions_executed += 1

        self._apply_customer_response(
            incident, case, nudge_number, now, alternate_offered=bool(alternate)
        )

    def _walk_to_link(self, case: dict[str, Any], now: int) -> None:
        """Move a case to the state a nudge is sent from, one legal transition at a time.

        A first nudge comes from DETECTED or DEFERRED and passes through ELIGIBLE and
        LINK_CREATED. A second nudge comes from WAITING, which the diagram sends straight back to
        NUGDED, so it must not be dragged through ELIGIBLE on the way.
        """
        state = CaseState(case["state"])
        if state == CaseState.WAITING:
            return
        if state in (CaseState.DETECTED, CaseState.DEFERRED):
            self._to_state(case, CaseState.ELIGIBLE, now)
        if CaseState(case["state"]) == CaseState.ELIGIBLE:
            self._to_state(case, CaseState.LINK_CREATED, now)

    def _ensure_eligible(self, case: dict[str, Any], now: int) -> None:
        """Move a case to ELIGIBLE if the diagram allows it from where it is.

        A case already waiting on a link has passed ELIGIBLE and does not go back.
        """
        state = CaseState(case["state"])
        if state in (CaseState.DETECTED, CaseState.DEFERRED):
            self._to_state(case, CaseState.ELIGIBLE, now)

    def _rail_broken_at(self, order_id: str, now: int) -> bool:
        """Whether the rail this order used was actually broken at `now`.

        Read from the simulator's fault schedule, not from the detector's incidents. A baseline
        does not detect anything, so judging it against incidents would either mark every one of
        its nudges as landing in a broken rail (the synthetic incident it acts under never closes)
        or make its measured outcome depend on how well the agent's detector happened to do. The
        world decides whether the rail was up.
        """
        if not self._world_faults:
            return False
        row = self._conn.execute(
            "SELECT method, upi_handle, card_bin, card_issuer, card_network, nb_bank "
            "FROM v_payment_attempts WHERE order_id = ? ORDER BY created_at LIMIT 1",
            (order_id,),
        ).fetchone()
        if row is None:
            return False
        instrument = {
            "method": row["method"],
            "upi_handle": row["upi_handle"],
            "card_bin": row["card_bin"],
            "card_issuer": row["card_issuer"],
            "card_network": row["card_network"],
            "nb_bank": row["nb_bank"],
        }
        for fault in self._world_faults:
            if not (int(fault["start"]) <= now < int(fault["end"])):
                continue
            selector = fault.get("selector") or {}
            if all(instrument.get(key) == value for key, value in selector.items()):
                return True
        return False

    # -- escalation to fix -------------------------------------------------

    def _repair_world(self, incident_id: str, fixed_at: int) -> None:
        """The world repairs what the escalation was about, escalation_fix_minutes later.

        World state, like `_world_faults`, and for the same reason: whether the rail a customer
        failed on has since been fixed is a fact about the world, not a decision Salvage takes.
        Nothing here is ledgered, because the ledger records what Salvage did and Salvage did not
        do this. What Salvage did was file the escalation, and that entry is already written.

        Two effects, and the second is deliberately the smaller of the two available:

          the repaired faults stop counting as broken, so a message after the repair is scored as
          landing on a working rail;

          every order the fault put at risk, that is still unpaid and still inside the model's
          organic horizon, gets one further chance to come back at its own organic probability,
          decayed for the time it has been waiting.

        The attempt stream was generated before any policy ran and is not rewritten, so payments
        the fault would have broken after the repair still fail in the recorded data. A real fix
        would have stopped them failing at all; here they get the same single chance to come back
        that everyone else the fault hit gets. That is less credit than a real fix earns, so the
        mechanism understates what a fix is worth, and it understates it for the only arm that can
        trigger one.

        The population is every order the fault put at risk, not only the ones that failed before
        the repair landed. Scoping it to the earlier ones made a fast fix score worse than a slow
        one, because a fast fix simply has fewer failures behind it, and the failures in front of
        it are exactly the ones it should have prevented. That is an artefact of the frozen stream
        and not a finding, so it is not modelled that way.
        """
        from salvage.eval.baselines import FaultWindow, at_risk_orders

        incident = repo.get_incident(self._conn, incident_id)
        if incident is None:
            return
        segment_key = str(incident["segment_key"])

        windows: list[FaultWindow] = []
        for index, fault in enumerate(self._world_faults):
            start, end = int(fault["start"]), int(fault["end"])
            if end <= fixed_at:
                # Already over. The world fixed it without anybody being told, and crediting the
                # escalation for that would be crediting it for the clock.
                continue
            selector = dict(fault.get("selector") or {})
            if not _fault_answers_segment(selector, segment_key):
                continue
            self._world_faults[index] = {**fault, "end": fixed_at}
            windows.append(FaultWindow(start=start, end=end, selector=selector))

        if not windows:
            return
        self.stats.fixes_applied += 1

        horizon = self._response.organic_horizon_seconds
        for order in at_risk_orders(self._conn, windows):
            if fixed_at - order.failed_at > horizon:
                # Repaired long after this customer stopped waiting. The model gives nobody a
                # retry beyond organic_retry_max_minutes and the repair does not get an exception.
                continue
            # An order that failed after the repair landed hears about it at the moment it fails,
            # not before, so its second chance starts from its own failure.
            starts_at = max(fixed_at, order.failed_at)
            row = repo.get_order(self._conn, order.order_id) or {}
            if _paid_by(row, starts_at):
                continue
            plan = self._response.repair_plan(
                order_index=_order_index(order.order_id),
                amount_paise=order.amount,
                error_reason=order.error_reason,
                first_failed_at=order.failed_at,
                fixed_at=starts_at,
            )
            if not plan.returns or plan.at is None:
                continue
            repo.mark_order_paid(self._conn, order.order_id, plan.at)
            if repo.record_recovery_route(
                self._conn,
                order_id=order.order_id,
                route="fix",
                paid_at=plan.at,
                policy=self._profile.name,
            ):
                self.stats.fix_recoveries += 1

    def _alternate_offer(
        self, incident: dict[str, Any], customer: dict[str, Any], now: int
    ) -> str | None:
        """The alternate method this message may offer, or None.

        Three things have to be true: the policy steers at all, the customer has another method,
        and a checkout hint is actually active for this incident. A policy that does not steer
        offers nothing, which is the whole difference the results are trying to measure.
        """
        if not self._profile.allows_steer:
            return None
        alternate = customer.get("alt_method")
        if not alternate:
            return None
        if self._active_hint(str(incident["id"])) is None:
            return None
        return str(alternate)

    def _apply_customer_response(
        self,
        incident: dict[str, Any],
        case: dict[str, Any],
        nudge_number: int,
        now: int,
        *,
        alternate_offered: bool,
    ) -> None:
        """What the customer does about the nudge, from the response model.

        Architecture section 9's multipliers. Every draw is keyed by order and nudge number, so
        B1's first nudge and the agent's first nudge to the same customer resolve against the same
        random value: the comparison in docs/RESULTS.md is between decisions, not between luck.
        """
        order = repo.get_order(self._conn, case["order_id"]) or {}
        order_index = _order_index(str(case["order_id"]))

        first_failure = self._conn.execute(
            "SELECT created_at, error_reason FROM v_payment_attempts WHERE order_id = ? "
            "AND status = 'failed' ORDER BY created_at LIMIT 1",
            (case["order_id"],),
        ).fetchone()
        failed_at = int(first_failure["created_at"]) if first_failure else now
        reason = first_failure["error_reason"] if first_failure else None

        still_failing = self._rail_broken_at(str(case["order_id"]), now)
        base = self._response.base_probability(
            amount_paise=int(order.get("amount") or 0), error_reason=reason
        )
        multiplier = self._response.intervention_multiplier(
            method_still_failing=still_failing,
            alternate_offered=alternate_offered,
            nudge_number=nudge_number,
            hours_since_failure=max(0.0, (now - failed_at) / 3600.0),
        )
        probability = self._response.apply_multiplier(base, multiplier)
        pays_draw, opt_out_draw, delay_draw = self._response.intervention_draw(
            order_index=order_index, nudge_number=nudge_number
        )

        if opt_out_draw < self._response.opt_out_probability(method_still_failing=still_failing):
            repo.set_opted_out(self._conn, str(case["customer_id"]), now)
            self._to_state(case, CaseState.OPTED_OUT, now)
            self.stats.opt_outs += 1
            self._ledger.append(
                "channel.opt_out",
                "case",
                str(case["id"]),
                {"incident_id": str(incident["id"]), "nudge_number": nudge_number},
                ts=now,
            )
            return

        if pays_draw < probability:
            delay = LINK_PAY_MIN_SECONDS + int(
                delay_draw * (LINK_PAY_MAX_SECONDS - LINK_PAY_MIN_SECONDS)
            )
            self._schedule(now + delay, "link_paid", str(case["id"]), str(incident["id"]), {})
            return

        # Only the agent decides when to try again. B1 sends once and B2 sends at 1 hour and 6
        # hours, both fixed by Architecture section 10, so a follow-up scheduled here would give
        # them a nudge their specification does not have.
        if self._profile.diagnoses and nudge_number < policy_mod.MAX_NUDGES_PER_INCIDENT:
            self._schedule(
                now + SECOND_NUDGE_DELAY_SECONDS,
                "second_nudge",
                str(case["id"]),
                str(incident["id"]),
                {},
            )

    # -- settlement --------------------------------------------------------

    def _settle(self, until: int) -> None:
        while self._timers and self._timers[0].at <= until:
            timer = heapq.heappop(self._timers)
            if timer.kind == "sweep":
                self._sweep(timer.incident_id, timer.at, timer.payload)
                continue
            if timer.kind == "steer_sweep":
                self._steer_sweep(timer.incident_id, timer.at, timer.payload)
                continue
            if timer.kind == "merchant_fix":
                self._repair_world(timer.incident_id, timer.at)
                continue
            case = repo.get_case(self._conn, timer.case_id)
            if case is None or is_terminal(case["state"]):
                continue
            incident = repo.get_incident(self._conn, timer.incident_id)
            if incident is None:
                continue
            now = timer.at

            if now > int(case["ttl_at"]):
                self._close_out(case, now)
                continue

            order = repo.get_order(self._conn, case["order_id"]) or {}
            paid_at = order.get("paid_at")
            if paid_at is not None and int(paid_at) <= now:
                # The customer paid on their own before the link resolved. The link is cancelled
                # and the case closes as PAID_ELSEWHERE, which is the honest attribution: the
                # agent did not recover this one.
                self._close_paid_elsewhere(case, now)
                continue

            if timer.kind == "link_paid":
                self._record_link_payment(case, incident, now)
            elif timer.kind in ("release_deferred", "release_quiet") or timer.kind == "fixed_nudge":
                self._apply_case_action(
                    incident, ActionType.SEND_RECOVERY_LINK, timer.payload, case, now
                )
            elif timer.kind == "second_nudge":
                self._apply_case_action(
                    incident, ActionType.SEND_RECOVERY_LINK, {"case_id": case["id"]}, case, now
                )

        # Anything still open when the run ends and past its TTL closes out. A case that was
        # never acted on closes as CLOSED_NO_ACTION rather than ABANDONED; see
        # salvage/execute/workflow.terminal_target_for.
        for case in self._conn.execute(
            "SELECT * FROM recovery_cases WHERE outcome IS NULL"
        ).fetchall():
            row = dict(case)
            order = repo.get_order(self._conn, str(row["order_id"])) or {}
            if _paid_by(order, until):
                # The order was paid while nothing was scheduled to notice. Closing it as
                # ABANDONED would have recorded a live link against a paid order, which is the
                # shape of a real policy violation even though nothing wrong happened.
                self._close_paid_elsewhere(row, int(order["paid_at"]))
                continue
            if until > int(row["ttl_at"]):
                self._close_out(row, until)

    def _steer_sweep(self, incident_id: str, now: int, payload: dict[str, Any]) -> None:
        """Recover orders that failed while a checkout steer was active.

        Architecture section 9: "a live checkout steer during the failing session gives a fixed
        0.55". Fixed means a probability, not a multiplier, so it replaces p_organic rather than
        scaling it, and it applies only to a customer who actually has another method to be
        steered onto. The draw is keyed by order, from its own stream, so a policy that never
        steers does not shift it.

        A steered recovery happens in the same session, so it is credited a few minutes after the
        failure rather than hours later. That timing matters: it is what lets a steer beat an
        organic retry to the same order.
        """
        incident = repo.get_incident(self._conn, incident_id)
        if incident is None:
            return
        hint_from = int(payload.get("hint_from") or now)
        closed_at = incident.get("closed_at")
        window_end = int(closed_at) if closed_at is not None else hint_from + 4 * 3600

        for order in self._steer_candidates(incident, hint_from, window_end):
            customer = repo.get_customer(self._conn, order.customer_id) or {}
            if not customer.get("alt_method"):
                continue
            self.stats.steer_opportunities += 1
            existing = repo.get_order(self._conn, order.order_id) or {}
            if _paid_by(existing, now):
                continue
            rng = order_stream(self._seed, "steer", _order_index(order.order_id))
            if float(rng.random()) >= self._response.steer_multiplier():
                continue
            paid_at = order.failed_at + STEER_PAY_SECONDS
            repo.mark_order_paid(self._conn, order.order_id, paid_at)
            if repo.record_recovery_route(
                self._conn,
                order_id=order.order_id,
                route="steer",
                paid_at=paid_at,
                policy=self._profile.name,
            ):
                self.stats.steer_recoveries += 1
                self.stats.steer_amount += order.amount
            self._ledger.append(
                "execute.steer_recovered",
                "order",
                order.order_id,
                {"incident_id": incident_id, "amount": order.amount},
                ts=paid_at,
            )

    def _steer_candidates(
        self, incident: dict[str, Any], start: int, end: int
    ) -> list[EligibleOrder]:
        """Eligible orders inside the steered segment that failed while the hint was active."""
        segment_key = str(incident["segment_key"])
        method, dimension, value = parse_key(segment_key)
        candidates = []
        for order in eligible_orders(self._conn, start=start, end=end):
            if segment_key != ALL_KEY and order.method != method:
                continue
            if dimension:
                row = self._conn.execute(
                    "SELECT upi_handle, card_bin, card_issuer, card_network, nb_bank "
                    "FROM v_payment_attempts WHERE order_id = ? ORDER BY created_at LIMIT 1",
                    (order.order_id,),
                ).fetchone()
                column = {
                    "upi_handle": "upi_handle",
                    "card_bin6": "card_bin",
                    "card_issuer": "card_issuer",
                    "card_network": "card_network",
                    "nb_bank": "nb_bank",
                }.get(dimension)
                if column and (row is None or row[column] != value):
                    continue
            candidates.append(order)
        return candidates

    def _sweep(self, incident_id: str, now: int, payload: dict[str, Any]) -> None:
        """Open cases for orders that failed since the last sweep, and apply the same plan."""
        incident = repo.get_incident(self._conn, incident_id)
        if incident is None:
            return
        closed_at = incident.get("closed_at")
        if closed_at is not None and now > int(closed_at) + SWEEP_INTERVAL_SECONDS:
            return
        cases = self._open_cases(incident, now)
        if not cases:
            return
        plan = Plan.model_validate(payload["plan"])
        self._apply_plan(incident, plan, cases, now)

    def _close_refused(self, case: dict[str, Any], *, matrix: bool, now: int) -> None:
        """Close a case whose action was refused, by a path the state diagram actually draws.

        A matrix refusal escalates, and ESCALATED is only reachable from ELIGIBLE, so a deferred
        case is walked back to ELIGIBLE first. Any other refusal ends the case: a case that was
        never acted on closes as CLOSED_NO_ACTION and one that was waiting closes as ABANDONED,
        which is what terminal_target_for encodes.
        """
        current = CaseState(case["state"])
        if matrix:
            if current in (CaseState.DEFERRED, CaseState.DETECTED):
                self._to_state(case, CaseState.ELIGIBLE, now)
                current = CaseState.ELIGIBLE
            if current == CaseState.ELIGIBLE:
                self._to_state(case, CaseState.ESCALATED, now)
                return
            self._close_out(case, now)
            return
        self._close_out(case, now)

    def _close_paid_elsewhere(self, case: dict[str, Any], now: int) -> None:
        """The order was paid by some other route. Cancel the link and close the case."""
        if case.get("link_id"):
            self._gateway.cancel_link(str(case["link_id"]))
        state = CaseState(case["state"])
        if state in (CaseState.NUDGED,):
            # NUDGED has no PAID_ELSEWHERE edge; the diagram sends it through WAITING first.
            self._to_state(case, CaseState.WAITING, now)
        self._to_state(case, CaseState.PAID_ELSEWHERE, now)

    def _close_out(self, case: dict[str, Any], now: int) -> None:
        """Walk a case to its terminal state, one legal transition at a time."""
        for _ in range(4):
            current = CaseState(case["state"])
            if is_terminal(current):
                return
            self._to_state(case, terminal_target_for(current), now)

    def _record_link_payment(
        self, case: dict[str, Any], incident: dict[str, Any], now: int
    ) -> None:
        order = repo.get_order(self._conn, case["order_id"]) or {}
        amount = int(order.get("amount") or 0)
        repo.mark_order_paid(self._conn, str(case["order_id"]), now)
        repo.record_recovery_route(
            self._conn,
            order_id=str(case["order_id"]),
            route="link",
            paid_at=now,
            policy=self._profile.name,
            case_id=str(case["id"]),
        )
        self._to_state(case, CaseState.RECOVERED, now)
        self.stats.recovered_cases += 1
        self.stats.recovered_amount += amount
        self._ledger.append(
            "execute.link_paid",
            "case",
            str(case["id"]),
            {
                "incident_id": str(incident["id"]),
                "link_id": case.get("link_id"),
                "amount": amount,
            },
            ts=now,
        )

    # -- helpers -----------------------------------------------------------

    def _active_hint(self, incident_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT hide_json, sequence_json FROM checkout_hints WHERE incident_id = ? "
            "ORDER BY active_from DESC LIMIT 1",
            (incident_id,),
        ).fetchone()
        if row is None:
            return None
        hide = json.loads(row["hide_json"])
        sequence = json.loads(row["sequence_json"])
        display: dict[str, Any] = {}
        if hide:
            display["hide"] = [{"method": method} for method in hide]
        if sequence:
            display["sequence"] = [f"block.{method}" for method in sequence]
            display["preferences"] = {"show_default_blocks": True}
        return display or None

    def _expiry_text(self, expire_by: int) -> str:
        hours = max(1, (expire_by - 0) // 3600 % 72 or 72)
        return f"{hours} hours"

    def _schedule(
        self, at: int, kind: str, case_id: str, incident_id: str, payload: dict[str, Any]
    ) -> None:
        self._sequence += 1
        heapq.heappush(
            self._timers,
            _Timer(
                at=at,
                sequence=self._sequence,
                kind=kind,
                case_id=case_id,
                incident_id=incident_id,
                payload=dict(payload),
            ),
        )

    def _to_state(self, case: dict[str, Any], target: CaseState, now: int) -> None:
        current = CaseState(case["state"])
        if current == target:
            return
        new_state = advance(current, target)
        outcome = outcome_for(new_state)
        self._conn.execute(
            "UPDATE recovery_cases SET state = ?, outcome = ?, updated_at = ? WHERE id = ?",
            (new_state.value, outcome, now, case["id"]),
        )
        case["state"] = new_state.value
        case["outcome"] = outcome

    def _record_action(
        self,
        incident_id: str,
        action_type: ActionType,
        case_id: str | None,
        params: dict[str, Any],
        status: str,
        gates: list[dict[str, Any]],
        now: int,
    ) -> None:
        self._action_serial += 1
        action_id = f"act_{incident_id}_{self._action_serial:05d}"
        repo.insert_action(
            self._conn,
            {
                "id": action_id,
                "case_id": case_id,
                "incident_id": incident_id,
                "type": action_type.value,
                "params_json": json.dumps(params, sort_keys=True, default=str),
                "gate_json": json.dumps(gates, sort_keys=True),
                "status": status,
                "rzp_request_id": None,
                "rzp_response_json": None,
                "executed_at": now,
            },
        )
        self._ledger.append(
            f"execute.action.{status}",
            "action",
            action_id,
            {
                "incident_id": incident_id,
                "case_id": case_id,
                "type": action_type.value,
                "params": params,
                "gates": gates,
            },
            ts=now,
        )

    def _refuse(
        self,
        incident_id: str,
        action_type: ActionType,
        case_id: str | None,
        params: dict[str, Any],
        verdict,
        now: int,
    ) -> None:
        self._record_action(
            incident_id, action_type, case_id, params, "refused", verdict.gates_json(), now
        )
        self.stats.actions_refused += 1
        if policy_mod.refused_for_matrix(verdict):
            self._escalate(
                incident_id,
                reason=f"matrix refusal: {verdict.refusing_rule}",
                packet=None,
                proposed={"type": action_type.value, "params": params},
                now=now,
            )

    def _escalate(
        self,
        incident_id: str,
        *,
        reason: str,
        packet,
        proposed: dict[str, Any] | None,
        now: int,
    ) -> None:
        existing = self._conn.execute(
            "SELECT COUNT(*) AS n FROM escalations WHERE incident_id = ? AND reason = ?",
            (incident_id, reason),
        ).fetchone()["n"]
        if existing:
            return
        escalation_id = f"esc_{incident_id}_{self.stats.escalations:03d}"
        repo.insert_escalation(
            self._conn,
            {
                "id": escalation_id,
                "incident_id": incident_id,
                "reason": reason,
                "evidence_json": packet.model_dump_json() if packet is not None else "{}",
                "proposed_action_json": json.dumps(proposed or {}, sort_keys=True, default=str),
                "decision": None,
                "decided_at": None,
                "note": None,
                "created_at": now,
            },
        )
        self._conn.execute("UPDATE incidents SET status = 'escalated' WHERE id = ?", (incident_id,))
        self.stats.escalations += 1
        # An escalation reaches a human, and in the world the human eventually fixes the thing.
        # How long that takes is the swept parameter; `never` schedules nothing at all.
        if self._escalation_fix_minutes is not None and incident_id not in self._repaired_incidents:
            self._repaired_incidents.add(incident_id)
            self._schedule(
                now + self._escalation_fix_minutes * 60,
                "merchant_fix",
                "",
                incident_id,
                {"escalated_at": now},
            )
        self._ledger.append(
            "escalation.opened",
            "escalation",
            escalation_id,
            {"incident_id": incident_id, "reason": reason, "proposed_action": proposed},
            ts=now,
        )


def _fault_answers_segment(selector: dict[str, Any], segment_key: str) -> bool:
    """Whether an escalation about `segment_key` would lead a human to this fault.

    The rule is "not contradicted", not "exactly equal". An incident attributed to `card` covers a
    fault on one BIN range, and an incident attributed to `card:card_network:Visa` does not rule
    out a gateway fault that was breaking every method. Only a genuine disagreement, an escalation
    about UPI against a fault on cards, fails to match.

    This is generous to the agent and docs/RESULTS.md says so: it assumes that a human pointed at
    the right incident finds the actual fault. The stingier reading, that only an exactly matching
    escalation gets fixed, would make the fix curve shallower. Nothing else in the mechanism is
    generous, so the assumption is isolated here where it can be argued with.
    """
    from salvage.detect.segments import ALL_KEY, INSTRUMENT_DIMENSIONS, parse_key

    if segment_key == ALL_KEY or not selector:
        return True
    method, dimension, value = parse_key(segment_key)
    if selector.get("method") not in (None, method):
        return False
    if dimension is None:
        return True
    selector_key = dict(INSTRUMENT_DIMENSIONS).get(dimension)
    if selector_key is None or selector_key not in selector:
        return True
    return str(selector[selector_key]) == str(value)


def _paid_by(order: dict[str, Any], now: int) -> bool:
    """Whether this order was already paid at time `now`.

    Not `status == "paid"`. The agent runs over a completed simulation, so an order the customer
    will pay at 22:30 already carries a paid status at 20:10, and a policy that read the status
    would be reading the future: it would decline to act on exactly the customers who were about
    to come back, and then take no credit and no blame for them. An order is unpaid until its
    payment time arrives.
    """
    paid_at = order.get("paid_at")
    return paid_at is not None and int(paid_at) <= now


def _order_index(order_id: str) -> int:
    """The simulator's order index out of its order id.

    The response model keys its draws on the order index, and the executor only has the order id.
    Simulator ids are order_sim<12 digits>; anything else falls back to a stable hash so a real
    Razorpay order still gets a deterministic draw.
    """
    if order_id.startswith("order_sim"):
        return int(order_id[len("order_sim") :])
    return abs(hash(order_id)) % 1_000_000_007
