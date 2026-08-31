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
    /*
     * A neutral operational record, not a red card.
     *
     * The whole panel used to be tinted and outlined in red, which is the generic alert-card look
     * and which spends the loudest colour in the palette on the container rather than on the
     * problem. Red now marks the fault and the fault only: the severity badge and the planner
     * error line. Everything around it is the same surface as the rest of the console, which is
     * exactly what makes the red mean something when you reach it.
     */
    <div
      className={`rounded-[var(--radius-sm)] border p-5 ${
        decided ? "border-[color:var(--border)]" : "border-[color:var(--border-strong)]"
      } bg-[color:var(--surface-raised)] ${fresh ? "flash" : ""}`}
    >
      {/* 1. Severity, 2. incident identity, 3. timestamp */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <Badge tone={plannerFailed ? "danger" : decided ? "neutral" : "warning"}>
          {plannerFailed ? "planner error" : decided ? escalation.decision : "waiting"}
        </Badge>
        <Link
          to={`/incidents/${escalation.incident_id}`}
          className="dt-mono text-[length:var(--fs-body)] text-[color:var(--accent)] hover:text-[color:var(--text-primary)]"
        >
          {escalation.incident
            ? segmentLabel(escalation.incident.segment_key)
            : escalation.incident_id}
        </Link>
        <span className="ml-auto dt-mono text-[color:var(--text-muted)]">
          {timestamp(escalation.created_at)}
        </span>
      </div>

      {/* 4. Why it stopped. Red only on the label, because the reason is the fault. */}
      {plannerFailed ? (
        <div className="mt-4 border-l-2 border-[color:var(--danger)] pl-4">
          <div className="text-[length:var(--fs-micro)] font-semibold uppercase tracking-[var(--ls-caps)] text-[color:var(--danger)]">
            Planner error
          </div>
          <div className="dt-mono mt-1 text-[color:var(--text-primary)]">{escalation.reason}</div>
          <p className="mt-2 max-w-[var(--measure)] text-[length:var(--fs-meta)] leading-[var(--lh-normal)] text-[color:var(--text-secondary)]">
            No action was chosen. The executor escalated because planning failed, which is not an
            agent deciding a human should take this one.
          </p>
        </div>
      ) : (
        <p className="mt-3 max-w-[var(--measure)] text-[length:var(--fs-body)] leading-[var(--lh-normal)] text-[color:var(--text-secondary)]">
          {REASONS[escalation.reason] ?? escalation.reason}
        </p>
      )}

      {/* 5. Confidence, 6. financial risk. One row, one grid, labels above values. */}
      {escalation.incident && (
        <dl className="mt-5 grid gap-x-8 gap-y-3 sm:grid-cols-3">
          <div>
            <dt className="text-[length:var(--fs-micro)] uppercase tracking-[var(--ls-caps)] text-[color:var(--text-muted)]">
              Cause
            </dt>
            <dd className="mt-1 text-[color:var(--text-primary)]">
              {causeLabel(escalation.incident.root_cause)}
            </dd>
          </div>
          <div>
            <dt className="text-[length:var(--fs-micro)] uppercase tracking-[var(--ls-caps)] text-[color:var(--text-muted)]">
              Confidence
            </dt>
            <dd className="dt-mono mt-1 text-[color:var(--text-primary)]">
              {escalation.incident.confidence === null
                ? "-"
                : escalation.incident.confidence.toFixed(2)}
            </dd>
          </div>
          <div>
            <dt className="text-[length:var(--fs-micro)] uppercase tracking-[var(--ls-caps)] text-[color:var(--text-muted)]">
              At risk
            </dt>
            <dd className="dt-mono mt-1 text-[color:var(--text-primary)]">
              {rupees(escalation.incident.at_risk_amount)}
            </dd>
          </div>
        </dl>
      )}

      {Object.keys(escalation.proposed_action ?? {}).length > 0 && (
        <div className="mt-5">
          <div className="text-[length:var(--fs-micro)] uppercase tracking-[var(--ls-caps)] text-[color:var(--text-muted)]">
            Proposed action
          </div>
          <div className="dt-mono mt-1 text-[color:var(--text-primary)]">
            {String(escalation.proposed_action.type ?? "action")}
            {escalation.proposed_action.scope ? (
              <span className="text-[color:var(--text-muted)]">
                {" "}
                for {String(escalation.proposed_action.scope)}
              </span>
            ) : null}
          </div>
          {typeof (escalation.proposed_action.params as Record<string, unknown> | undefined)
            ?.reason === "string" ? (
            <p className="mt-1 max-w-[var(--measure)] text-[length:var(--fs-meta)] leading-[var(--lh-normal)] text-[color:var(--text-secondary)]">
              {String((escalation.proposed_action.params as Record<string, unknown>).reason)}
            </p>
          ) : null}
        </div>
      )}

      <Disclosure summary="evidence summary" className="mt-5">
        <Code>{JSON.stringify(escalation.evidence, null, 2)}</Code>
      </Disclosure>

      {decided ? (
        <div className="mt-2 text-[length:var(--fs-meta)]">
          <Badge tone={escalation.decision === "approve" ? "success" : "neutral"}>
            {escalation.decision}
          </Badge>{" "}
          <span className="num text-[color:var(--text-secondary)]">{timestamp(escalation.decided_at)}</span>
          <div className="mt-1 text-[color:var(--text-primary)]">{escalation.note}</div>
        </div>
      ) : (
        <div className="mt-5 flex flex-wrap items-start gap-3">
          <ConfirmButton
            label="Approve"
            confirmLabel="Approve"
            tone="success"
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
            tone="danger"
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
                <summary className="cursor-pointer text-[length:var(--fs-meta)] text-[color:var(--info)] hover:text-[color:var(--text-primary)]">
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
