import type { ReplayState } from "../../replay/state";
import type { RecordingMeta } from "../../replay/types";
import { count, timeOnly } from "../../lib/format";

/**
 * The plan, and then the gate ladder that decided what actually happened to it.
 *
 * This is the page. Everything else is context for it.
 *
 * The policy engine writes every gate it evaluated onto the entry, in the order it evaluated
 * them, with the sentence it wrote about each one. So the ladder here is not a reconstruction: it
 * is the record. The first gate that failed is the rule that decided the outcome, and it is pulled
 * out above the ladder at a size that reads from across a room, because a refusal a viewer has to
 * hunt for is a refusal they will not believe happened.
 *
 * A refusal is given exactly as much room as an action. That is the point of the whole system: an
 * agent that will not do something, and can say which rule stopped it, is the difference between
 * this and a script that sends messages.
 */

const STATUS_WORD: Record<string, string> = {
  executed: "Executed",
  refused: "Refused",
  deferred: "Deferred",
  queued: "Queued",
  failed: "Failed",
};

const STATUS_SEVERITY: Record<string, string> = {
  executed: "ok",
  refused: "crit",
  deferred: "warn",
  queued: "warn",
  failed: "crit",
};

export function Gates({ state, meta }: { state: ReplayState; meta: RecordingMeta }) {
  const action = state.currentAction;
  // The ladder holds the last action evaluated, which is often not the entry the head is on: half
  // the beats on this run are a detection, a recovery or a close. It stays on screen rather than
  // emptying, because a panel that blanks between actions is unreadable when the page is paused,
  // and it says which of the two it is showing.
  const isCurrent = action !== null && state.frame !== null && action.ord === state.frame.ord;

  return (
    <div className="col2">
      <div>
        <div className="lbl mb-2">Plan</div>
        {state.plan ? (
          <div className="panel p-4">
            {state.plan.planner_error && (
              <div className="alert mb-3">
                <div className="lbl crit">Planner failed</div>
                <div className="txt mt-1">{state.plan.planner_error}</div>
                <div className="note mt-2">
                  A planner that cannot plan does not fall back to doing something to customers. It
                  falls back to asking a person, so the plan below is the escalation default and not
                  a choice the model made.
                </div>
              </div>
            )}
            <p className="txt">{state.plan.plan.rationale}</p>
            <div className="divide mt-3">
              {state.plan.plan.actions.map((planned, index) => (
                <div key={`${planned.type}-${index}`} className="flex items-baseline gap-3 py-2">
                  <span className="mono text-[12.5px]">{planned.type}</span>
                  <span className="note mono">{planned.scope}</span>
                </div>
              ))}
            </div>
            <div className="kv mt-4">
              <span className="lbl">Affected orders</span>
              <span className="mono mid text-[12px]">
                {count(state.plan.eligibility.affected_orders)}
              </span>
              <span className="lbl">Consented</span>
              <span className="mono mid text-[12px]">
                {count(state.plan.eligibility.consented)}
              </span>
              <span className="lbl">With an alternate</span>
              <span className="mono mid text-[12px]">
                {count(state.plan.eligibility.consented_with_alternate)}
              </span>
              <span className="lbl">Opted out</span>
              <span className="mono mid text-[12px]">{count(state.plan.eligibility.opted_out)}</span>
              <span className="lbl">Hard declined</span>
              <span className="mono mid text-[12px]">
                {count(state.plan.eligibility.hard_declined)}
              </span>
            </div>
            <p className="note mt-3">
              Counts, and nothing else. This is everything the planner learns about the customers,
              so it cannot reason about an individual even if it wanted to.
            </p>
          </div>
        ) : (
          <div className="panel p-4">
            <p className="note">No plan yet. The planner runs once the incident is diagnosed.</p>
          </div>
        )}

        <div className="lbl mb-2 mt-6">Outcomes so far</div>
        <div className="board">
          {["executed", "refused", "deferred", "queued", "failed"].map((status) => {
            const value = state.statusCounts[status] ?? 0;
            if (value === 0 && status === "failed") return null;
            return (
              <div key={status} className="cell">
                <div className={`lbl ${value > 0 ? STATUS_SEVERITY[status] : ""}`}>
                  {STATUS_WORD[status]}
                </div>
                <div className="fig-lg mt-1">{count(value)}</div>
              </div>
            );
          })}
        </div>

        {state.refusalsByRule.length > 0 && (
          <>
            <div className="lbl mb-2 mt-6">Refusals by the rule that decided them</div>
            <div className="panel divide">
              {state.refusalsByRule.map((entry) => (
                <div key={entry.rule} className="flex items-baseline gap-3 px-4 py-2.5">
                  <span className="fig-md crit">{count(entry.count)}</span>
                  <span className="mono text-[12px]">{entry.rule}</span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      <div>
        <div className="mb-2 flex items-baseline justify-between gap-3">
          <span className="lbl">Gate ladder</span>
          {action && (
            <span className="note">
              {isCurrent ? "the entry the head is on" : "the last action evaluated"}
            </span>
          )}
        </div>
        {action ? (
          <>
            <div className={`verdict verdict-${action.status}${isCurrent ? " held" : ""}`}>
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <span className={`chip ${STATUS_SEVERITY[action.status] ?? "info"}`}>
                  <span className="dot" aria-hidden="true" />
                  {STATUS_WORD[action.status] ?? action.status}
                </span>
                <span className="note mono">
                  {timeOnly(action.ts)}
                  {action.seq !== null ? ` · seq ${action.seq}` : ""}
                </span>
              </div>
              <div className="mono mid mt-2 text-[13px]">{action.type}</div>
              <div className="lbl mt-3">
                {action.decided ? "Decided by" : "Every gate passed"}
              </div>
              <div
                className={`verdict-rule mt-1 ${action.decided ? "crit" : "ok"}`}
              >
                {action.decided ? action.decided.rule : "no rule refused it"}
              </div>
              {action.decided && <p className="txt mt-2">{action.decided.detail}</p>}
              {action.caseId && (
                <div className="note mono mt-3">{action.caseId}</div>
              )}
            </div>

            <div className="ladder mt-3">
              {action.gates.map((gate, index) => (
                <div
                  key={`${gate.rule}-${index}`}
                  className={`gate${gate.passed ? "" : " gate-failed"}`}
                >
                  <span
                    className={`gate-mark ${gate.passed ? "ok" : "crit"}`}
                    aria-label={gate.passed ? "passed" : "refused"}
                  >
                    {gate.passed ? "pass" : "stop"}
                  </span>
                  <span className="gate-rule">{gate.rule}</span>
                  <span className="gate-detail">{gate.detail}</span>
                </div>
              ))}
              {action.gates.length === 0 && (
                <div className="gate">
                  <span className="gate-mark dim">-</span>
                  <span className="gate-rule">no gates</span>
                  <span className="gate-detail">
                    An incident-level action the matrix always allows evaluates no rules, and the
                    entry records an empty ladder rather than a fabricated one.
                  </span>
                </div>
              )}
            </div>
            <p className="note mt-3">
              The ladder stops at the rule that refused it, because the policy engine stops there
              too. The confidence gate reads the reconciled number against the{" "}
              {meta.thresholds.action_confidence} action threshold, and the sentence beside every
              rule is the one the engine wrote when it made the call.
            </p>
          </>
        ) : (
          <div className="panel p-4">
            <p className="note">
              No action evaluated yet. The first one lands the moment the plan does.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
