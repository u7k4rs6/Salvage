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
 *
 * Colour follows the palette's meanings and nothing else: blue is diagnosis, amber is pending,
 * teal is recovered, red is an incident or a refusal. The accent never appears here, because
 * every box on this row is a state.
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
  const refused = actions.filter((action) => action.status === "refused");
  const escalated = data.incident.escalated || kinds.has("escalation.opened");
  const executedReal = actions.filter(
    (action) => action.status === "executed" && action.type !== "ESCALATE_HUMAN",
  );
  const recovered = data.cases.filter((row) => row.outcome === "RECOVERED").length;

  const spine: Stage[] = [
    {
      key: "detect",
      status: kinds.has("detect.incident.opened") ? "done" : "idle",
      colour: "var(--incident)",
      detail: data.incident.segment_key,
    },
    {
      key: "diagnose",
      status: kinds.has("diagnose.reconciled") ? "done" : "idle",
      colour: "var(--diagnosis)",
      detail: data.diagnosis?.reconciled
        ? data.diagnosis.reconciled.replace(/_/g, " ")
        : "no verdict",
    },
    {
      key: "plan",
      status: kinds.has("decide.plan") ? "done" : "idle",
      colour: "var(--diagnosis)",
      detail: `${actions.length} action${actions.length === 1 ? "" : "s"}`,
    },
    {
      key: "gate",
      status: gated.length > 0 ? "done" : "idle",
      // A gate that refused is a refusal, and refusals are red. A gate that passed is not.
      colour: refused.length > 0 ? "var(--incident)" : "var(--pending)",
      detail:
        gated.length > 0
          ? `${gated.reduce((sum, action) => sum + action.gate.length, 0)} rules`
          : "no rules evaluated",
    },
  ];

  const execute: Stage = {
    key: "execute",
    status: executedReal.length > 0 ? (recovered > 0 ? "done" : "active") : "idle",
    colour: "var(--text)",
    detail: `${executedReal.length} executed`,
  };
  const escalate: Stage = {
    key: "escalate",
    status: escalated ? "active" : "idle",
    colour: "var(--pending)",
    detail: escalated ? "awaiting a human" : "not taken",
  };
  const recover: Stage = {
    key: "recover",
    status: recovered > 0 ? "done" : "idle",
    colour: "var(--recovered)",
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
      <div className="flex items-center gap-2">
        <span
          aria-hidden="true"
          className="inline-block h-1.5 w-1.5 rounded-full"
          style={{ background: stage.status === "idle" ? "var(--text-3)" : stage.colour }}
        />
        <span
          className="microlabel"
          style={{ color: stage.status === "idle" ? "var(--text-3)" : "var(--text)" }}
        >
          {stage.key}
        </span>
      </div>
      <div
        className="mono mt-2 max-w-[10rem] truncate"
        style={{
          fontSize: 11,
          color: stage.status === "idle" ? "var(--text-3)" : "var(--text-2)",
        }}
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
      <div className="flex items-stretch overflow-x-auto pb-2">
        {spine.map((stage, index) => (
          <div key={stage.key} className="flex items-stretch">
            <StageBox stage={stage} />
            {index < spine.length - 1 && (
              <div className="flex items-center px-2">
                <div className={`connector ${stage.status === "done" ? "connector-done" : ""}`} />
              </div>
            )}
          </div>
        ))}

        {/* The fork. Two branches out of GATE, on two rows, so neither can be read as continuing
            into the other. */}
        <div className="flex items-center px-2">
          <div className={`connector ${spine[3].status === "done" ? "connector-done" : ""}`} />
        </div>
        <div className="flex flex-col gap-2">
          <div className="flex items-stretch">
            <StageBox stage={execute} />
            <div className="flex items-center px-2">
              <div className={`connector ${execute.status === "done" ? "connector-done" : ""}`} />
            </div>
            <StageBox stage={recover} />
          </div>
          <div className="flex items-stretch">
            <StageBox stage={escalate} />
            <div className="flex items-center px-2">
              <div
                className="terminal-stop"
                style={{ opacity: escalate.status === "idle" ? 0.25 : 1 }}
              />
            </div>
            <div className="flex items-center">
              <span
                className="microlabel"
                style={{ color: escalate.status === "idle" ? "var(--text-3)" : "var(--pending)" }}
              >
                terminal
              </span>
            </div>
          </div>
        </div>
      </div>
      <p className="body-sm mt-6 max-w-2xl">
        Escalate is where the agent stops and a human takes over. Nothing runs from it to recover,
        here or in the system.
      </p>
    </div>
  );
}
