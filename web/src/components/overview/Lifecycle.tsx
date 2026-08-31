import type { IncidentDetail } from "../../lib/types";

/**
 * The pipeline an incident walks: DETECT, DIAGNOSE, PLAN, GATE, then a fork.
 *
 * EXECUTE leads to RECOVER. ESCALATE does not. It is a terminal branch and it is drawn as one,
 * with a stop bar and nothing after it, because a line running from ESCALATE onward to RECOVER
 * would claim something this project's own results disprove: an escalated incident is handed to a
 * human and the agent stops there.
 *
 * Every stage is read from the incident's ledger slice and its plan, never assumed. A stage with
 * no evidence renders idle, GATE included, which is genuinely not reached when the only action
 * taken is one the matrix always allows.
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
  const executed = actions.filter(
    (action) => action.status === "executed" && action.type !== "ESCALATE_HUMAN",
  );
  const recovered = data.cases.filter((row) => row.outcome === "RECOVERED").length;

  const spine: Stage[] = [
    {
      key: "detect",
      status: kinds.has("detect.incident.opened") ? "done" : "idle",
      colour: "var(--info)",
      detail: data.incident.segment_key,
    },
    {
      key: "diagnose",
      status: kinds.has("diagnose.reconciled") ? "done" : "idle",
      colour: "var(--info)",
      detail: data.diagnosis?.reconciled?.replace(/_/g, " ") ?? "no verdict",
    },
    {
      key: "plan",
      status: kinds.has("decide.plan") ? "done" : "idle",
      colour: "var(--info)",
      detail: `${actions.length} action${actions.length === 1 ? "" : "s"}`,
    },
    {
      key: "gate",
      // A gate that refused is a refusal, and refusals are red. A gate that passed is not.
      status: gated.length > 0 ? "done" : "idle",
      colour: refused.length > 0 ? "var(--crit)" : "var(--warn)",
      detail:
        gated.length > 0
          ? `${gated.reduce((sum, action) => sum + action.gate.length, 0)} rules`
          : "no rules evaluated",
    },
  ];

  return {
    spine,
    execute: {
      key: "execute",
      status: executed.length > 0 ? (recovered > 0 ? "done" : "active") : "idle",
      colour: "var(--info)",
      detail: `${executed.length} executed`,
    } as Stage,
    escalate: {
      key: "escalate",
      status: escalated ? "active" : "idle",
      colour: "var(--warn)",
      detail: escalated ? "awaiting a human" : "not taken",
    } as Stage,
    recover: {
      key: "recover",
      status: recovered > 0 ? "done" : "idle",
      colour: "var(--ok)",
      detail: `${recovered} case${recovered === 1 ? "" : "s"}`,
    } as Stage,
  };
}

function Box({ stage }: { stage: Stage }) {
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
          className="dot"
          style={{ background: stage.status === "idle" ? "var(--fg-3)" : stage.colour }}
        />
        <span className={`lbl ${stage.status === "idle" ? "" : "lbl-2"}`}>{stage.key}</span>
      </div>
      <div
        className={`mono mt-1.5 max-w-[9rem] truncate text-[11px] ${
          stage.status === "idle" ? "dim" : "mid"
        }`}
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
            <Box stage={stage} />
            {index < spine.length - 1 && (
              <div className="flex items-center px-1.5">
                <div className={`connector ${stage.status === "done" ? "connector-done" : ""}`} />
              </div>
            )}
          </div>
        ))}

        {/* The fork. Two branches out of GATE, on two rows, so neither reads as continuing into
            the other. */}
        <div className="flex items-center px-1.5">
          <div className={`connector ${spine[3].status === "done" ? "connector-done" : ""}`} />
        </div>
        <div className="flex flex-col gap-1.5">
          <div className="flex items-stretch">
            <Box stage={execute} />
            <div className="flex items-center px-1.5">
              <div className={`connector ${execute.status === "done" ? "connector-done" : ""}`} />
            </div>
            <Box stage={recover} />
          </div>
          <div className="flex items-stretch">
            <Box stage={escalate} />
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
      <p className="note mt-3">
        Escalate is terminal. Nothing runs from it to recover, here or in the system.
      </p>
    </div>
  );
}
