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
import type { Escalation } from "../lib/types";

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
      className={`border p-3 ${decided ? "border-neutral-300" : "border-amber-300 bg-amber-50"} ${
        fresh ? "flash" : ""
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={decided ? "neutral" : "amber"}>{escalation.reason}</Badge>
        <Link
          to={`/incidents/${escalation.incident_id}`}
          className="num text-sm text-accent hover:text-accent-hover"
        >
          {escalation.incident
            ? segmentLabel(escalation.incident.segment_key)
            : escalation.incident_id}
        </Link>
        <span className="num text-xs text-neutral-600">{timestamp(escalation.created_at)}</span>
      </div>

      <p className="mt-1 text-xs text-neutral-700">
        {REASONS[escalation.reason] ?? "Escalated for a reason the console does not have text for."}
      </p>

      {escalation.incident && (
        <div className="mt-2 grid gap-2 text-xs sm:grid-cols-3">
          <div>
            <span className="text-neutral-600">cause </span>
            <span className="num">{causeLabel(escalation.incident.root_cause)}</span>
          </div>
          <div>
            <span className="text-neutral-600">confidence </span>
            <span className="num">
              {escalation.incident.confidence === null
                ? "-"
                : escalation.incident.confidence.toFixed(2)}
            </span>
          </div>
          <div>
            <span className="text-neutral-600">at risk </span>
            <span className="num">{rupees(escalation.incident.at_risk_amount)}</span>
          </div>
        </div>
      )}

      {Object.keys(escalation.proposed_action ?? {}).length > 0 && (
        <div className="num mt-2 text-xs text-neutral-800">
          proposed {String(escalation.proposed_action.type ?? "action")}{" "}
          <span className="text-neutral-500">{JSON.stringify(escalation.proposed_action)}</span>
        </div>
      )}

      <Disclosure summary="evidence summary" className="mt-2">
        <Code>{JSON.stringify(escalation.evidence, null, 2)}</Code>
      </Disclosure>

      {decided ? (
        <div className="mt-2 text-xs">
          <Badge tone={escalation.decision === "approve" ? "green" : "neutral"}>
            {escalation.decision}
          </Badge>{" "}
          <span className="num text-neutral-600">{timestamp(escalation.decided_at)}</span>
          <div className="mt-1 text-neutral-800">{escalation.note}</div>
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
                <summary className="cursor-pointer text-xs text-accent hover:text-accent-hover">
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
