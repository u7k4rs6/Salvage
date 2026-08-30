import type { ReplayState, Stage } from "../../replay/state";
import { count } from "../../lib/format";

/**
 * Where the incident is right now.
 *
 * Same track as the Overview's, driven from the replay's own state instead of from a fetched
 * incident, and with the same rule about its shape: escalate is a terminal branch. It is reachable
 * from the gates and nothing is reachable from it, so it is drawn with a stop bar and nothing
 * after it. A line from escalate onward to recover would claim something the system does not do.
 *
 * A stage is "done" only when the replay has consumed an entry that says so. Nothing is lit
 * because the run will get there later.
 */

type Status = "done" | "active" | "idle";

interface Node {
  key: string;
  status: Status;
  colour: string;
  detail: string;
  /** A second line, where one number does not describe the stage. Only the gate has one. */
  sub?: string;
  /** Provenance under the detail, muted. */
  tert?: string;
}

const ORDER: Stage[] = ["detect", "diagnose", "plan", "execute", "recover"];

function statusFor(stage: Stage, current: Stage, reached: boolean): Status {
  if (!reached) return "idle";
  if (stage === current) return "active";
  const here = ORDER.indexOf(stage);
  const now = ORDER.indexOf(current);
  if (here >= 0 && now >= 0 && here < now) return "done";
  return "done";
}

export function Track({ state, stage }: { state: ReplayState; stage: Stage }) {
  const gated = state.actions.filter((action) => action.gates.length > 0);
  const rules = gated.reduce((sum, action) => sum + action.gates.length, 0);
  const refused = state.statusCounts.refused ?? 0;
  const executed = state.statusCounts.executed ?? 0;
  // The rule that has refused the most so far, which is the one the ladder keeps landing on.
  const topRule = state.refusalsByRule.reduce<{ rule: string; count: number } | null>(
    (best, entry) => (best === null || entry.count > best.count ? entry : best),
    null,
  );
  const recovered = state.recoveredByLink + state.recoveredBySteer;

  const spine: Node[] = [
    {
      key: "detect",
      status: statusFor("detect", stage, Boolean(state.incident)),
      colour: "var(--info)",
      detail: state.incident ? state.incident.segmentKey : "nothing open",
    },
    {
      key: "diagnose",
      status: statusFor("diagnose", stage, Boolean(state.diagnosis)),
      colour: "var(--info)",
      detail: state.diagnosis ? state.diagnosis.rootCause.replace(/_/g, " ") : "no verdict",
    },
    {
      key: "plan",
      status: statusFor("plan", stage, Boolean(state.plan)),
      colour: "var(--info)",
      detail: state.plan ? `${state.plan.plan.actions.length} actions` : "no plan",
    },
    {
      key: "gate",
      status: gated.length > 0 ? "done" : "idle",
      colour: refused > 0 ? "var(--crit)" : "var(--warn)",
      // What the ladder is about is what was refused and by which rule, not how many rules were
      // looked at on the way. The evaluation total is real and it is the least interesting number
      // on the page, so it sits underneath at the smallest size.
      detail:
        gated.length > 0
          ? `${count(refused)} refused, ${count(executed)} executed`
          : "no rules evaluated",
      sub: topRule ? topRule.rule : undefined,
      tert: gated.length > 0 ? `${count(rules)} rules evaluated` : undefined,
    },
  ];

  const execute: Node = {
    key: "execute",
    status:
      (state.statusCounts.executed ?? 0) > 0 ? (stage === "execute" ? "active" : "done") : "idle",
    colour: "var(--info)",
    detail: `${count(state.statusCounts.executed ?? 0)} executed`,
  };
  const recover: Node = {
    key: "recover",
    status: recovered > 0 ? (stage === "recover" ? "active" : "done") : "idle",
    colour: "var(--ok)",
    detail: `${count(recovered)} recovered`,
  };
  const escalate: Node = {
    key: "escalate",
    status: state.escalation ? "active" : "idle",
    colour: "var(--warn)",
    detail: state.escalation ? "awaiting a human" : "not taken",
  };

  return (
    <div>
      <div className="flex items-stretch overflow-x-auto pb-1">
        {spine.map((node, index) => (
          <div key={node.key} className="flex items-stretch">
            <Box node={node} />
            {index < spine.length - 1 && (
              <div className="flex items-center px-1.5">
                <div className={`connector ${node.status !== "idle" ? "connector-done" : ""}`} />
              </div>
            )}
          </div>
        ))}

        <div className="flex items-center px-1.5">
          <div className={`connector ${spine[3].status !== "idle" ? "connector-done" : ""}`} />
        </div>
        <div className="flex flex-col gap-1.5">
          <div className="flex items-stretch">
            <Box node={execute} />
            <div className="flex items-center px-1.5">
              <div className={`connector ${execute.status === "done" ? "connector-done" : ""}`} />
            </div>
            <Box node={recover} />
          </div>
          <div className="flex items-stretch">
            <Box node={escalate} />
            <div className="flex items-center px-1.5">
              <div
                className="terminal-stop"
                style={{ opacity: escalate.status === "idle" ? 0.3 : 1 }}
              />
            </div>
            <div className="flex items-center">
              <span className={`lbl ${escalate.status === "idle" ? "" : "warn"}`}>terminal</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Box({ node }: { node: Node }) {
  const cls =
    node.status === "done"
      ? "stage stage-done"
      : node.status === "active"
        ? "stage stage-active"
        : "stage stage-idle";
  return (
    <div className={cls} style={node.status === "active" ? { color: node.colour } : undefined}>
      <div className="flex items-center gap-1.5">
        <span
          aria-hidden="true"
          className="dot"
          style={{ background: node.status === "idle" ? "var(--fg-3)" : node.colour }}
        />
        <span className={`lbl ${node.status === "idle" ? "" : "lbl-2"}`}>{node.key}</span>
      </div>
      <div
        className={`mono mt-1.5 max-w-[12rem] truncate text-[11px] ${
          node.status === "idle" ? "dim" : "mid"
        }`}
        title={node.detail}
      >
        {node.detail}
      </div>
      {node.sub && (
        <div
          className={`mono mt-0.5 max-w-[12rem] truncate text-[11px] ${
            node.status === "idle" ? "dim" : "crit"
          }`}
          title={node.sub}
        >
          {node.sub}
        </div>
      )}
      {node.tert && (
        <div className="tert mt-0.5 max-w-[12rem] truncate" title={node.tert}>
          {node.tert}
        </div>
      )}
      <span className="sr-only">
        {node.status === "done"
          ? "complete"
          : node.status === "active"
            ? "current stage"
            : "not reached"}
      </span>
    </div>
  );
}
