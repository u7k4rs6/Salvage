import { useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../lib/useApi";
import { useSession } from "../lib/session";
import { useStream } from "../lib/useStream";
import { post } from "../lib/api";
import {
  Badge,
  Code,
  ConfirmButton,
  Disclosure,
  Empty,
  Panel,
  Region,
} from "../components/primitives";
import { causeLabel, rupees, segmentLabel, timestamp } from "../lib/format";
import { isPlannerFailureReason } from "../lib/health";
import type { Escalation } from "../lib/types";
import { PageIntro } from "../components/PageIntro";

interface EscalationList {
  clock: string;
  status: string;
  escalations: Escalation[];
}

const REASONS: Record<string, string> = {
  merchant_side_cause: "The cause is on the merchant's side, so the agent does not act alone.",
  low_confidence: "Confidence fell below the threshold.",
  matrix_refusal: "The action and cause matrix does not allow this action for this cause.",
  circuit_breaker: "The circuit breaker tripped and paused the agent.",
  disagreement: "Rules and model disagreed.",
};

function Card({
  escalation,
  onDecided,
  fresh,
}: {
  escalation: Escalation;
  onDecided: () => void;
  fresh: boolean;
}) {
  const { token } = useSession();
  const decided = escalation.decision !== null;
  // A planner failure and a considered handover both arrive here as an escalation and mean opposite
  // things. The Overview separates them; this page did not, so a run whose planner had no fixture
  // read as the agent deciding a human should take an issuer outage. Same test, same words.
  const plannerFailed = isPlannerFailureReason(escalation.reason);

  async function decide(decision: "approve" | "reject", note: string) {
    await post(
      `/api/escalations/${escalation.id}/decision`,
      { decision, note },
      token,
    );
    onDecided();
  }

  return (
    <div
      className={`border p-3 ${
        decided
          ? "border-[color:var(--line-2)]"
          : plannerFailed
            ? "border-[color:var(--crit)] bg-[color:var(--crit-bg)]"
            : "border-[color:var(--warn)] bg-[color:var(--warn-bg)]"
      } ${
        fresh ? "flash" : ""
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={decided ? "neutral" : plannerFailed ? "red" : "amber"}>
          {plannerFailed ? "planner error" : escalation.reason}
        </Badge>
        <Link
          to={`/incidents/${escalation.incident_id}`}
          className="num text-[length:var(--fs-small)] text-[color:var(--info)] hover:text-[color:var(--fg)]"
        >
          {escalation.incident
            ? segmentLabel(escalation.incident.segment_key)
            : escalation.incident_id}
        </Link>
        <span className="num text-[length:var(--fs-small)] text-[color:var(--fg-2)]">{timestamp(escalation.created_at)}</span>
      </div>

      {plannerFailed ? (
        <div className="mt-2 border border-[color:var(--crit)] border-l-2 bg-[color:var(--crit-bg)] px-3 py-2">
          <div className="flex flex-wrap items-baseline gap-x-3">
            <span className="text-[length:var(--fs-caption)] font-medium uppercase tracking-[0.08em] text-[color:var(--crit)]">
              Planner error
            </span>
            <span className="num text-[length:var(--fs-small)] text-[color:var(--fg)]">{escalation.reason}</span>
          </div>
          <p className="mt-1.5 max-w-[var(--measure)] text-[length:var(--fs-small)] leading-[var(--lh-normal)] text-[color:var(--fg-2)]">
            No action was chosen. The executor escalated because planning failed, which is not an
            agent deciding a human should take this one.
          </p>
        </div>
      ) : (
        <p className="mt-1 text-[length:var(--fs-small)] text-[color:var(--fg-2)] max-w-[var(--measure)]">
          {REASONS[escalation.reason] ?? "Escalated for a reason the console does not have text for."}
        </p>
      )}

      {escalation.incident && (
        <div className="mt-2 grid gap-2 text-[length:var(--fs-small)] sm:grid-cols-3">
          <div>
            <span className="text-[color:var(--fg-2)]">cause </span>
            <span className="num">{causeLabel(escalation.incident.root_cause)}</span>
          </div>
          <div>
            <span className="text-[color:var(--fg-2)]">confidence </span>
            <span className="num">
              {escalation.incident.confidence === null
                ? "-"
                : escalation.incident.confidence.toFixed(2)}
            </span>
          </div>
          <div>
            <span className="text-[color:var(--fg-2)]">at risk </span>
            <span className="num">{rupees(escalation.incident.at_risk_amount)}</span>
          </div>
        </div>
      )}

      {Object.keys(escalation.proposed_action ?? {}).length > 0 && (
        <div className="num mt-2 text-[length:var(--fs-small)] text-[color:var(--fg)]">
          proposed {String(escalation.proposed_action.type ?? "action")}{" "}
          <span className="text-[color:var(--fg-3)]">{JSON.stringify(escalation.proposed_action)}</span>
        </div>
      )}

      <Disclosure summary="evidence summary" className="mt-2">
        <Code>{JSON.stringify(escalation.evidence, null, 2)}</Code>
      </Disclosure>

      {decided ? (
        <div className="mt-2 text-[length:var(--fs-small)]">
          <Badge tone={escalation.decision === "approve" ? "green" : "neutral"}>
            {escalation.decision}
          </Badge>{" "}
          <span className="num text-[color:var(--fg-2)]">{timestamp(escalation.decided_at)}</span>
          <div className="mt-1 text-[color:var(--fg)]">{escalation.note}</div>
        </div>
      ) : (
        <div className="mt-3 flex flex-wrap gap-2">
          <ConfirmButton
            label="Approve"
            confirmLabel="Approve"
            tone="green"
            prompt="Approve this action. The note is recorded in the ledger with your decision."
            requireNote
            notePlaceholder="Why this is the right call"
            disabled={!token}
            disabledReason={token ? undefined : "enter the token"}
            onConfirm={(note) => decide("approve", note)}
          />
          <ConfirmButton
            label="Reject"
            confirmLabel="Reject"
            tone="red"
            prompt="Reject this action. The note is recorded in the ledger with your decision."
            requireNote
            notePlaceholder="Why not"
            disabled={!token}
            disabledReason={token ? undefined : "enter the token"}
            onConfirm={(note) => decide("reject", note)}
          />
        </div>
      )}
    </div>
  );
}

export default function EscalationsPage() {
  const pending = useApi<EscalationList>("/api/escalations?status=pending");
  const decided = useApi<EscalationList>("/api/escalations?status=decided");
  const [freshIds, setFreshIds] = useState<string[]>([]);

  useStream(["escalation.opened", "escalation.decided"], (event) => {
    const id = String(event.data.id ?? "");
    if (event.name === "escalation.opened" && id) {
      setFreshIds((current) => [...current, id]);
      window.setTimeout(() => setFreshIds((current) => current.filter((value) => value !== id)), 400);
    }
    pending.reload();
    decided.reload();
  });

  function reloadBoth() {
    pending.reload();
    decided.reload();
  }

  return (
    <div className="space-y-4">
      <PageIntro
        title="Escalations"
        what="Everything the agent stopped and handed to a person instead of acting on."
        use="Read the reason, open the evidence, then approve or reject with a written note. Both need the dashboard token pasted into the top bar."
        shows={[
          ["Waiting on you", "escalations nobody has decided yet. Nothing customer-facing happens on these until somebody does"],
          ["Reason", "why it stopped: low confidence, a cause the action matrix forbids acting on, a rules and model disagreement, or a tripped circuit breaker"],
          ["Planner error", "a red card means planning failed, rather than the agent deciding a human should take this one. Those two look alike and mean opposite things"],
          ["Proposed", "what the agent would have done, so the decision is about a specific action rather than a vague handover"],
          ["Decided", "the history, with the note whoever decided it wrote"],
        ]}
      />
      <Panel
        title="Waiting on you"
        subtitle="The agent stopped and asked. Nothing here has been acted on."
      >
        <Region state={pending} rows={3}>
          {(data) =>
            data.escalations.length === 0 ? (
              <Empty>Nothing waiting on you.</Empty>
            ) : (
              <div className="space-y-3">
                {data.escalations.map((escalation) => (
                  <Card
                    key={escalation.id}
                    escalation={escalation}
                    onDecided={reloadBoth}
                    fresh={freshIds.includes(escalation.id)}
                  />
                ))}
              </div>
            )
          }
        </Region>
      </Panel>

      <Panel title="Decided" subtitle="History, newest first.">
        <Region state={decided} rows={2}>
          {(data) =>
            data.escalations.length === 0 ? (
              <Empty>No decisions yet.</Empty>
            ) : (
              <details>
                <summary className="cursor-pointer text-[length:var(--fs-small)] text-[color:var(--info)] hover:text-[color:var(--fg)]">
                  {data.escalations.length} decided
                </summary>
                <div className="mt-2 space-y-2">
                  {data.escalations.map((escalation) => (
                    <Card
                      key={escalation.id}
                      escalation={escalation}
                      onDecided={reloadBoth}
                      fresh={false}
                    />
                  ))}
                </div>
              </details>
            )
          }
        </Region>
      </Panel>
    </div>
  );
}
