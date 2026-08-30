import { actionStatusOf, decidingRule, type Frame, type Replay } from "./model";
import type {
  ActionPayload,
  EscalationOpenedPayload,
  GateRecord,
  IncidentClosedPayload,
  IncidentOpenedPayload,
  LinkPaidPayload,
  PlanPayload,
  ReconciledPayload,
  SteerRecoveredPayload,
} from "./types";

/**
 * The whole screen, as a pure function of one frame ordinal.
 *
 * There is no animation state anywhere on this page. Every panel reads a field of the object this
 * returns, and this is rebuilt by folding the frames from the first up to the cursor. A recording
 * is five hundred frames, so rebuilding it on every step costs nothing and buys the one property
 * the page exists for: what is on screen cannot drift from what the recording says, because there
 * is nothing else for it to be.
 */

export interface ActionRecord {
  ord: number;
  ts: number;
  seq: number | null;
  hash: string | null;
  status: string;
  type: string;
  caseId: string | null;
  gates: GateRecord[];
  /** The first gate that failed, the rule that decided the outcome. Null when every gate passed. */
  decided: GateRecord | null;
}

export interface CaseRecord {
  id: string;
  state: string;
  since: number;
  /** Where the state was read from, so the page can say so rather than imply a chain entry. */
  source: "ledger" | "cases";
}

export interface DiagnosisRecord {
  ts: number;
  rulesCause: string;
  rulesDetail: string;
  llmCause: string | null;
  rationale: string;
  rootCause: string;
  confidence: number;
  agreed: boolean | null;
  escalate: boolean;
  escalationReason: string | null;
  evidence: ReconciledPayload["evidence"];
}

export interface IncidentRecord {
  id: string;
  segmentKey: string;
  scope: string[];
  openedAt: number;
  windowStart: number;
  windowEnd: number;
  atRisk: number;
  closedAt: number | null;
}

export type Stage =
  | "idle"
  | "detect"
  | "diagnose"
  | "plan"
  | "execute"
  | "escalate"
  | "recover"
  | "closed";

export interface ReplayState {
  ord: number;
  frame: Frame | null;

  incident: IncidentRecord | null;
  diagnosis: DiagnosisRecord | null;
  plan: PlanPayload | null;
  escalation: { ts: number; reason: string } | null;

  actions: ActionRecord[];
  /** The action the gate ladder is showing: the most recent one consumed. */
  currentAction: ActionRecord | null;
  statusCounts: Record<string, number>;
  /** Refusals per deciding rule, in the order the rules were first seen. */
  refusalsByRule: { rule: string; detail: string; count: number }[];

  cases: Map<string, CaseRecord>;
  caseCounts: { state: string; count: number }[];
  /**
   * Links created. Nothing records link creation on its own, so this counts the first executed
   * SEND_RECOVERY_LINK per case, which is the moment the executor created the link before
   * recording the action at that same timestamp.
   */
  linksCreated: number;
  recoveredByLink: number;
  recoveredBySteer: number;
  recoveredAmount: number;
  optOuts: number;

  /** The most recent frames, newest first, for the ledger tail. */
  tail: Frame[];
}

const TAIL_LENGTH = 14;

/**
 * The case state an action was evaluated against.
 *
 * The `case.not_terminal` gate's detail carries the case's state at the moment the policy engine
 * looked at it. That is the only per-case state the chain reports, and it is exact, so it is read
 * rather than inferred from the sequence of actions.
 */
function caseStateFromGates(gates: GateRecord[]): string | null {
  const gate = gates.find((entry) => entry.rule === "case.not_terminal");
  if (!gate) return null;
  const match = /^case state (\w+)$/.exec(gate.detail);
  return match ? match[1] : null;
}

function bump(counts: Map<string, number>, key: string): void {
  counts.set(key, (counts.get(key) ?? 0) + 1);
}

export function stateAt(replay: Replay, ord: number): ReplayState {
  let incident: IncidentRecord | null = null;
  let diagnosis: DiagnosisRecord | null = null;
  let plan: PlanPayload | null = null;
  let escalation: { ts: number; reason: string } | null = null;

  const actions: ActionRecord[] = [];
  const statusCounts = new Map<string, number>();
  const refusals = new Map<string, { rule: string; detail: string; count: number }>();

  const cases = new Map<string, CaseRecord>();
  const linkCases = new Set<string>();
  let recoveredByLink = 0;
  let recoveredBySteer = 0;
  let recoveredAmount = 0;
  let optOuts = 0;

  const setCase = (id: string, state: string, ts: number, source: "ledger" | "cases") => {
    cases.set(id, { id, state, since: ts, source });
  };

  const last = Math.min(ord, replay.frames.length - 1);
  for (let index = 0; index <= last; index += 1) {
    const frame = replay.frames[index];

    if (frame.kind.startsWith("execute.action.")) {
      const payload = frame.payload as ActionPayload;
      const status = actionStatusOf(frame.kind);
      const gates = payload.gates ?? [];
      const decided = decidingRule(gates);
      actions.push({
        ord: frame.ord,
        ts: frame.ts,
        seq: frame.seq,
        hash: frame.hash,
        status,
        type: payload.type,
        caseId: payload.case_id,
        gates,
        decided,
      });
      bump(statusCounts, status);
      if (status === "refused" && decided) {
        const existing = refusals.get(decided.rule);
        if (existing) existing.count += 1;
        else refusals.set(decided.rule, { rule: decided.rule, detail: decided.detail, count: 1 });
      }
      if (payload.case_id) {
        // The ladder reports the state the case was in before this action, so it only fills in a
        // case the replay has not seen yet.
        const observed = caseStateFromGates(gates);
        if (observed && !cases.has(payload.case_id)) {
          setCase(payload.case_id, observed, frame.ts, "ledger");
        }
        if (status === "executed" && payload.type === "SEND_RECOVERY_LINK") {
          linkCases.add(payload.case_id);
          setCase(payload.case_id, "WAITING", frame.ts, "ledger");
        } else if (status === "deferred") {
          setCase(payload.case_id, "DEFERRED", frame.ts, "ledger");
        }
      }
      continue;
    }

    switch (frame.kind) {
      case "detect.incident.opened": {
        const payload = frame.payload as IncidentOpenedPayload;
        incident = {
          id: frame.refId,
          segmentKey: payload.segment_key,
          scope: payload.affected_scope,
          openedAt: frame.ts,
          windowStart: payload.window_start,
          windowEnd: payload.window_end,
          atRisk: payload.at_risk_amount,
          closedAt: null,
        };
        break;
      }
      case "detect.incident.closed": {
        const payload = frame.payload as IncidentClosedPayload;
        if (incident !== null && incident.id === frame.refId) {
          incident.closedAt = payload.closed_at;
        }
        break;
      }
      case "detect.incident.resegmented": {
        const payload = frame.payload as { from: string; to: string; affected_scope: string[] };
        if (incident !== null && incident.id === frame.refId) {
          // Mutated rather than replaced: this object is built fresh on every call and nothing
          // outside this function has seen it yet.
          incident.segmentKey = payload.to;
          incident.scope = payload.affected_scope;
        }
        break;
      }
      case "diagnose.reconciled": {
        const payload = frame.payload as ReconciledPayload;
        diagnosis = {
          ts: frame.ts,
          rulesCause: payload.rules_cause,
          rulesDetail: payload.rules_detail,
          llmCause: payload.llm_cause,
          rationale: payload.rationale,
          rootCause: payload.root_cause,
          confidence: payload.confidence,
          agreed: payload.agreed,
          escalate: payload.escalate,
          escalationReason: payload.escalation_reason,
          evidence: payload.evidence,
        };
        break;
      }
      case "decide.plan": {
        plan = frame.payload as PlanPayload;
        break;
      }
      case "escalation.opened": {
        const payload = frame.payload as EscalationOpenedPayload;
        escalation = { ts: frame.ts, reason: payload.reason };
        break;
      }
      case "execute.link_paid": {
        const payload = frame.payload as LinkPaidPayload;
        recoveredByLink += 1;
        recoveredAmount += payload.amount;
        setCase(frame.refId, "RECOVERED", frame.ts, "ledger");
        break;
      }
      case "execute.steer_recovered": {
        const payload = frame.payload as SteerRecoveredPayload;
        recoveredBySteer += 1;
        recoveredAmount += payload.amount;
        break;
      }
      case "channel.opt_out": {
        optOuts += 1;
        setCase(frame.refId, "OPTED_OUT", frame.ts, "ledger");
        break;
      }
      case "case.abandoned":
      case "case.paid_elsewhere": {
        const payload = frame.payload as { case_id: string; state: string };
        setCase(payload.case_id, payload.state, frame.ts, "cases");
        break;
      }
      default:
        break;
    }
  }

  const caseTally = new Map<string, number>();
  for (const record of cases.values()) bump(caseTally, record.state);

  const tailStart = Math.max(0, last - TAIL_LENGTH + 1);
  const tail = last < 0 ? [] : replay.frames.slice(tailStart, last + 1).reverse();

  return {
    ord,
    frame: last >= 0 ? replay.frames[last] : null,
    incident,
    diagnosis,
    plan,
    escalation,
    actions,
    currentAction: actions.length > 0 ? actions[actions.length - 1] : null,
    statusCounts: Object.fromEntries(statusCounts),
    refusalsByRule: [...refusals.values()],
    cases,
    caseCounts: [...caseTally.entries()]
      .map(([state, count]) => ({ state, count }))
      .sort((a, b) => b.count - a.count || a.state.localeCompare(b.state)),
    linksCreated: linkCases.size,
    recoveredByLink,
    recoveredBySteer,
    recoveredAmount,
    optOuts,
    tail,
  };
}

/**
 * Where the incident sits on the lifecycle track.
 *
 * Escalate is terminal. It is reachable from the gates and nothing is reachable from it, so it is
 * returned as a resting state rather than as a step on the way to anything.
 */
export function stageOf(state: ReplayState): Stage {
  if (!state.incident) return "idle";
  if (state.incident.closedAt !== null) return "closed";
  if (state.escalation) return "escalate";
  if (state.recoveredByLink > 0 || state.recoveredBySteer > 0) return "recover";
  if (state.actions.length > 0) return "execute";
  if (state.plan) return "plan";
  if (state.diagnosis) return "diagnose";
  return "detect";
}
