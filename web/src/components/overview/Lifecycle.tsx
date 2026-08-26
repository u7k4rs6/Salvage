import type { IncidentDetail } from "../../lib/types";

/**
 * The pipeline an incident actually walks: DETECT, DIAGNOSE, PLAN, GATE, then a fork.
 *
 * EXECUTE leads to RECOVER. ESCALATE does not. It is a terminal branch and it is drawn as one,
 * with a stop bar and nothing after it, because a line from ESCALATE onward to RECOVER would make
 * a claim this project's own results disprove: an escalated incident is handed to a human and the
 * agent stops there.
 *
 * Every stage is read from the incident's own ledger slice and its plan, never assumed. A stage
 * with no evidence renders idle, including GATE, which is genuinely not reached when the only
 * action taken is one the matrix always allows.
 */

type Status = "done" | "active" | "idle";

interface Stage {
  key: string;
  status: Status;
  colour: string;
  detail: string;
}

function stagesFor(data: IncidentDetail) {
  const kinds = new Set(data.timeline.map((entry) => entry.kind));
  const actions = data.plan?.actions ?? [];
  const gated = actions.filter((action) => action.gate.length > 0);
  const escalated = data.incident.escalated || kinds.has("escalation.opened");
  const executedReal = actions.filter(
    (action) => action.status === "executed" && action.type !== "ESCALATE_HUMAN",
  );
  const recovered = data.cases.filter((row) => row.outcome === "RECOVERED").length;

  const spine: Stage[] = [
    {
      key: "detect",
      status: kinds.has("detect.incident.opened") ? "done" : "idle",
      colour: "var(--detect)",
      detail: data.incident.segment_key,
    },
    {
      key: "diagnose",
      status: kinds.has("diagnose.reconciled") ? "done" : "idle",
      colour: "var(--diagnose)",
      detail: data.diagnosis?.reconciled
        ? data.diagnosis.reconciled.replace(/_/g, " ")
        : "no verdict",
    },
    {
      key: "plan",
      status: kinds.has("decide.plan") ? "done" : "idle",
      colour: "var(--diagnose)",
      detail: `${actions.length} action${actions.length === 1 ? "" : "s"}`,
    },
    {
      key: "gate",
      status: gated.length > 0 ? "done" : "idle",
      colour: "var(--gate)",
      detail:
        gated.length > 0
          ? `${gated.reduce((sum, action) => sum + action.gate.length, 0)} rules`
          : "no rules evaluated",
    },
  ];

  const execute: Stage = {
    key: "execute",
    status: executedReal.length > 0 ? (recovered > 0 ? "done" : "active") : "idle",
    colour: "var(--execute)",
    detail: `${executedReal.length} executed`,
  };
  const escalate: Stage = {
    key: "escalate",
    status: escalated ? "active" : "idle",
    colour: "var(--escalate)",
    detail: escalated ? "awaiting a human" : "not taken",
  };
  const recover: Stage = {
    key: "recover",
    status: recovered > 0 ? "done" : "idle",
    colour: "var(--recover)",
    detail: `${recovered} case${recovered === 1 ? "" : "s"}`,
  };

  return { spine, execute, escalate, recover };
}

function StageBox({ stage }: { stage: Stage }) {
  const cls =
    stage.status === "done"
      ? "stage stage-done"
      : stage.status === "active"
        ? "stage stage-active"
        : "stage stage-idle";
  return (
    <div className={cls} style={stage.status === "active" ? { color: stage.colour } : undefined}>
      <div className="flex items-center gap-1.5">
        <span
          aria-hidden="true"
          className="inline-block h-1.5 w-1.5 rounded-full"
          style={{ background: stage.status === "idle" ? "var(--ink-3)" : stage.colour }}
        />
        <span
          className="label"
          style={{ color: stage.status === "idle" ? "var(--ink-3)" : "var(--ink)" }}
        >
          {stage.key}
        </span>
      </div>
      <div
        className="mt-1 max-w-[10rem] truncate text-[11px]"
        style={{ color: stage.status === "idle" ? "var(--ink-3)" : "var(--ink-2)" }}
        title={stage.detail}
      >
        {stage.detail}
      </div>
      <span className="sr-only">
        {stage.status === "done"
          ? "complete"
          : stage.status === "active"
            ? "current stage"
            : "not reached"}
      </span>
    </div>
  );
}

export function Lifecycle({ data }: { data: IncidentDetail }) {
  const { spine, execute, escalate, recover } = stagesFor(data);

  return (
    <div>
      <div className="flex items-stretch overflow-x-auto pb-1">
        {spine.map((stage, index) => (
          <div key={stage.key} className="flex items-stretch">
            <StageBox stage={stage} />
            {index < spine.length - 1 && (
              <div className="flex items-center px-1.5">
                <div className={`connector ${stage.status === "done" ? "connector-done" : ""}`} />
              </div>
            )}
          </div>
        ))}

        {/* The fork. Two branches out of GATE, on two rows, so neither can be read as continuing
            into the other. */}
        <div className="flex items-center px-1.5">
          <div className={`connector ${spine[3].status === "done" ? "connector-done" : ""}`} />
        </div>
        <div className="flex flex-col gap-1.5">
          <div className="flex items-stretch">
            <StageBox stage={execute} />
            <div className="flex items-center px-1.5">
              <div className={`connector ${execute.status === "done" ? "connector-done" : ""}`} />
            </div>
            <StageBox stage={recover} />
          </div>
          <div className="flex items-stretch">
            <StageBox stage={escalate} />
            <div className="flex items-center px-1.5">
              <div
                className="terminal-stop"
                style={{ opacity: escalate.status === "idle" ? 0.25 : 1 }}
              />
            </div>
            <div className="flex items-center">
              <span
                className="label"
                style={{ color: escalate.status === "idle" ? "var(--ink-3)" : "var(--escalate)" }}
              >
                terminal
              </span>
            </div>
          </div>
        </div>
      </div>
      <p className="mt-3 max-w-2xl text-[11.5px] leading-snug text-[color:var(--ink-2)]">
        Escalate is where the agent stops and a human takes over. Nothing runs from it to recover,
        here or in the system.
      </p>
    </div>
  );
}
