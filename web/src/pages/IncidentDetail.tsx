import { Link, useParams } from "react-router-dom";
import { useApi } from "../lib/useApi";
import { useSession } from "../lib/session";
import { useStream } from "../lib/useStream";
import { post } from "../lib/api";
import {
  Badge,
  Cell,
  Code,
  ConfirmButton,
  Disclosure,
  Empty,
  Panel,
  Region,
  StatusBadge,
  Table,
  type Column,
} from "../components/primitives";
import { DistributionPair } from "../components/Distributions";
import { Timeline } from "../components/Timeline";
import { causeLabel, count, percent, rupees, segmentLabel, timestamp } from "../lib/format";
import type { Diagnosis, Evidence, IncidentDetail, Plan, RecoveryCase } from "../lib/types";
import { PageIntro } from "../components/PageIntro";

// The threshold the reconciler uses. Marked on the bar so the reader can see which side of it
// this incident fell on rather than being told the answer.
const CONFIDENCE_THRESHOLD = 0.6;

function EvidencePanel({ evidence }: { evidence: Evidence }) {
  return (
    <Panel
      title="Evidence"
      subtitle={`The packet the diagnosis was given. Window ${timestamp(
        evidence.window_start,
      )} to ${timestamp(evidence.window_end)}.`}
    >
      <div className="grid gap-3 sm:grid-cols-4">
        <div>
          <div className="text-[length:var(--fs-meta)] text-[color:var(--text-secondary)]">attempts</div>
          <div className="num text-[length:var(--fs-section)] font-semibold">{count(evidence.attempts)}</div>
        </div>
        <div>
          <div className="text-[length:var(--fs-meta)] text-[color:var(--text-secondary)]">failure rate</div>
          <div className="num text-[length:var(--fs-section)] font-semibold text-[color:var(--danger)]">{percent(evidence.rate)}</div>
        </div>
        <div>
          <div className="text-[length:var(--fs-meta)] text-[color:var(--text-secondary)]">baseline</div>
          <div className="num text-[length:var(--fs-section)] font-semibold">{percent(evidence.baseline_rate)}</div>
        </div>
        <div>
          <div className="text-[length:var(--fs-meta)] text-[color:var(--text-secondary)]">excess failures</div>
          <div className="num text-[length:var(--fs-section)] font-semibold">{count(evidence.excess_failures)}</div>
        </div>
      </div>

      <div className="mt-4 grid gap-6 lg:grid-cols-3">
        <DistributionPair title="error source" distribution={evidence.error_source_dist} />
        <DistributionPair title="error step" distribution={evidence.error_step_dist} />
        <DistributionPair title="error reason" distribution={evidence.error_reason_dist} />
      </div>

      <div className="mt-4">
        <h4 className="text-[length:var(--fs-meta)] font-medium uppercase tracking-wide text-[color:var(--text-secondary)]">
          sibling segments
        </h4>
        <div className="mt-1 flex flex-wrap gap-1">
          {Object.keys(evidence.sibling_segments ?? {}).length === 0 ? (
            <span className="text-[length:var(--fs-meta)] text-[color:var(--text-secondary)]">
              No siblings. This segment has no peer to compare against, which is itself part of
              the evidence.
            </span>
          ) : (
            Object.entries(evidence.sibling_segments).map(([key, health]) => (
              <Badge key={key} tone={health === "healthy" ? "success" : "danger"}>
                <span className="num">
                  {key} {health}
                </span>
              </Badge>
            ))
          )}
        </div>
      </div>

      <div className="mt-4 grid gap-3 text-[length:var(--fs-meta)] sm:grid-cols-4">
        <div>
          <span className="text-[color:var(--text-secondary)]">share of merchant volume </span>
          <span className="num">{percent(evidence.share_of_merchant_volume)}</span>
        </div>
        <div>
          <span className="text-[color:var(--text-secondary)]">minutes since onset </span>
          <span className="num">{count(evidence.minutes_since_onset)}</span>
        </div>
        <div>
          <span className="text-[color:var(--text-secondary)]">trend </span>
          <span className="num">{evidence.trend}</span>
        </div>
        <div>
          <span className="text-[color:var(--text-secondary)]">merchant config changed recently </span>
          <span className="num">{String(evidence.merchant_config_changed_recently)}</span>
        </div>
      </div>

      <div className="mt-4">
        <h4 className="text-[length:var(--fs-meta)] font-medium uppercase tracking-wide text-[color:var(--text-secondary)]">
          sample descriptions
        </h4>
        <p className="mb-1 text-[length:var(--fs-micro)] text-[color:var(--warning)]">
          Untrusted text, shown as data. These strings come from the gateway and are never treated
          as instructions.
        </p>
        <Code>{evidence.sample_descriptions.join("\n")}</Code>
      </div>
    </Panel>
  );
}

function ConfidenceBar({ confidence }: { confidence: number }) {
  return (
    <div className="relative mt-1 h-3 w-full max-w-md border border-[color:var(--border-strong)] bg-[color:var(--surface-raised)]">
      <div
        className={`h-full ${confidence >= CONFIDENCE_THRESHOLD ? "bg-[color:var(--success)]" : "bg-[color:var(--warning)]"}`}
        style={{ width: `${Math.round(confidence * 100)}%` }}
      />
      <div
        className="absolute top-0 h-full border-l-2 border-[color:var(--text-primary)]"
        style={{ left: `${CONFIDENCE_THRESHOLD * 100}%` }}
        title={`threshold ${CONFIDENCE_THRESHOLD}`}
      />
    </div>
  );
}

function DiagnosisPanel({ diagnosis }: { diagnosis: Diagnosis }) {
  return (
    <Panel
      title="Diagnosis"
      subtitle="Rules and model run on the same packet. The reconciler decides what happens when they disagree."
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <div>
          <div className="text-[length:var(--fs-meta)] text-[color:var(--text-secondary)]">rules</div>
          <div className="num text-[length:var(--fs-meta)]">{causeLabel(diagnosis.rules)}</div>
          {diagnosis.rules_detail && (
            <div className="mt-1 text-[length:var(--fs-micro)] text-[color:var(--text-secondary)]">{diagnosis.rules_detail}</div>
          )}
        </div>
        <div>
          <div className="text-[length:var(--fs-meta)] text-[color:var(--text-secondary)]">model</div>
          <div className="num text-[length:var(--fs-meta)]">{causeLabel(diagnosis.llm)}</div>
        </div>
        <div>
          <div className="text-[length:var(--fs-meta)] text-[color:var(--text-secondary)]">reconciled</div>
          <div className="num text-[length:var(--fs-meta)] font-semibold">{causeLabel(diagnosis.reconciled)}</div>
          <Badge tone={diagnosis.agreed ? "success" : "warning"}>
            {diagnosis.agreed ? "agreed" : "disagreed"}
          </Badge>
        </div>
      </div>

      {diagnosis.confidence !== null && (
        <div className="mt-3">
          <div className="text-[length:var(--fs-meta)] text-[color:var(--text-secondary)]">
            confidence <span className="num">{diagnosis.confidence.toFixed(2)}</span>, threshold{" "}
            <span className="num">{CONFIDENCE_THRESHOLD}</span>
          </div>
          <ConfidenceBar confidence={diagnosis.confidence} />
        </div>
      )}

      {diagnosis.escalate && (
        <div className="mt-3 border border-[color:var(--warning)] bg-[color:var(--warning-bg)] px-3 py-2 text-[length:var(--fs-meta)] text-[color:var(--warning)]">
          Escalated: {diagnosis.escalation_reason ?? "reason not recorded"}
        </div>
      )}

      {diagnosis.rationale && (
        <p className="mt-3 whitespace-pre-wrap text-[length:var(--fs-meta)] text-[color:var(--text-primary)]">{diagnosis.rationale}</p>
      )}

      <Disclosure summary="Show prompt and raw response" className="mt-3">
        {diagnosis.prompt || diagnosis.raw_response ? (
          <div className="space-y-2">
            <div>
              <div className="text-[length:var(--fs-meta)] text-[color:var(--text-secondary)]">prompt</div>
              <Code>{diagnosis.prompt ?? "not recorded"}</Code>
            </div>
            <div>
              <div className="text-[length:var(--fs-meta)] text-[color:var(--text-secondary)]">raw response</div>
              <Code>{diagnosis.raw_response ?? "not recorded"}</Code>
            </div>
          </div>
        ) : (
          <p className="text-[length:var(--fs-meta)] text-[color:var(--text-secondary)]">
            No prompt was recorded for this incident. Either no model ran, or the diagnosis came
            from cache.
          </p>
        )}
      </Disclosure>
    </Panel>
  );
}

function PlanPanel({ plan }: { plan: Plan }) {
  return (
    <Panel
      title="Plan"
      subtitle="What the planner proposed and what the policy engine did with it. A refused action names the rule that refused it."
    >
      {plan.rationale && (
        <p className="mb-3 whitespace-pre-wrap text-[length:var(--fs-meta)] text-[color:var(--text-primary)]">{plan.rationale}</p>
      )}

      {plan.proposed.length > 0 && (
        <div className="mb-3 space-y-1">
          {plan.proposed.map((action, index) => (
            <div key={index} className="num text-[length:var(--fs-meta)] text-[color:var(--text-secondary)]">
              proposed {action.type} over {action.scope}{" "}
              <span className="text-[color:var(--text-muted)]">{JSON.stringify(action.params)}</span>
            </div>
          ))}
        </div>
      )}

      {plan.actions.length === 0 ? (
        <Empty>No action reached the policy engine.</Empty>
      ) : (
        <ul className="space-y-2">
          {plan.actions.map((action) => {
            const refused = action.status === "refused";
            const deferred = action.status === "deferred";
            return (
              <li key={action.id} className="border border-[color:var(--border)] p-2">
                <div className="flex items-center gap-2">
                  <span
                    className={`num text-[length:var(--fs-meta)] font-medium ${refused ? "text-[color:var(--text-muted)] line-through" : ""}`}
                  >
                    {action.type}
                  </span>
                  <Badge tone={refused ? "danger" : deferred ? "warning" : "success"}>
                    {action.status}
                  </Badge>
                  {action.case_id && (
                    <span className="num text-[length:var(--fs-micro)] text-[color:var(--text-muted)]">{action.case_id}</span>
                  )}
                </div>
                <ul className="mt-1 space-y-0.5">
                  {action.gate.map((check) => (
                    <li key={check.rule} className="num text-[length:var(--fs-micro)]">
                      <span className={check.passed ? "text-[color:var(--success)]" : "text-[color:var(--danger)]"}>
                        {check.passed ? "pass" : "fail"}
                      </span>{" "}
                      <span className="text-[color:var(--text-primary)]">{check.rule}</span>{" "}
                      <span className="text-[color:var(--text-muted)]">{check.detail}</span>
                    </li>
                  ))}
                </ul>
                <Disclosure summary="params" className="mt-1">
                  <Code>{JSON.stringify(action.params, null, 2)}</Code>
                </Disclosure>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}

function CasesPanel({ cases }: { cases: RecoveryCase[] }) {
  return (
    <Panel
      title={`Cases (${cases.length})`}
      subtitle="One row per order the incident put at risk. State names are the state machine's, verbatim."
    >
      {cases.length === 0 ? (
        <Empty>No recovery cases were opened for this incident.</Empty>
      ) : (
        <div className="max-h-[32rem] overflow-y-auto">
          <Table columns={CASE_COLUMNS} minWidth="62rem">
            {cases.map((item) => (
              <tr key={item.id}>
                <Cell column="customer">
                  <span className="dt-mono">{item.ref_hash}</span>
                </Cell>
                <Cell column="order">
                  <span className="dt-mono">{item.order_id}</span>
                </Cell>
                <Cell column="amount">{rupees(item.amount)}</Cell>
                <Cell column="state">
                  <Badge
                    tone={
                      item.state === "RECOVERED"
                        ? "success"
                        : item.state === "ABANDONED" || item.state.startsWith("CLOSED")
                          ? "neutral"
                          : "warning"
                    }
                  >
                    {item.state}
                  </Badge>
                </Cell>
                <Cell column="nudges">{item.nudges}</Cell>
                <Cell column="link">
                  <span className="dt-mono">{item.link_id ?? "-"}</span>
                </Cell>
                <Cell column="next">
                  <span className="dt-mono whitespace-nowrap">
                    {item.next_action_at ? timestamp(item.next_action_at) : "-"}
                  </span>
                </Cell>
              </tr>
            ))}
          </Table>
        </div>
      )}
    </Panel>
  );
}

const CASE_COLUMNS: Column[] = [
  { key: "customer", label: "Customer", align: "text", flex: 1.6 },
  { key: "order", label: "Order", align: "text", flex: 1.8 },
  { key: "amount", label: "Amount", align: "num", flex: 1.1 },
  { key: "state", label: "State", align: "status", flex: 1.3 },
  { key: "nudges", label: "Actions", align: "num", flex: 0.9 },
  { key: "link", label: "Link", align: "text", flex: 1.5 },
  { key: "next", label: "Next action", align: "text", flex: 1.8 },
];

export default function IncidentDetailPage() {
  const { incidentId } = useParams();
  const { token } = useSession();
  const state = useApi<IncidentDetail>(incidentId ? `/api/incidents/${incidentId}` : null);
  useStream(
    ["incident.updated", "incident.closed", "action.executed", "action.refused"],
    (event) => {
      if (event.data.id === incidentId || event.data.incident_id === incidentId) state.reload();
    },
  );

  return (
    <div className="space-y-4">
      <PageIntro
        title="Incident detail"
        what="One incident from the first failure to the last thing the agent did about it."
        use="Read down: what the evidence was, what the diagnosis made of it, what was planned, then what each rule allowed or refused."
        shows={[
          ["Evidence", "exactly what the diagnosis was given: failure rate against this segment's own baseline, which errors, and whether sibling segments are healthy. No customer detail is in it, by construction"],
          ["Diagnosis", "the rules verdict and the model verdict side by side, then the reconciled cause. Agreement raises confidence, disagreement pushes it below the 0.6 threshold and escalates"],
          ["Plan", "what the agent decided to do, chosen from a fixed menu of five things. It cannot invent a sixth"],
          ["Actions", "every action with the rules it was checked against. A refusal names the rule that stopped it"],
          ["Cases", "one per affected order, and the state each reached"],
          ["Ledger slice", "the chain entries for this incident alone"],
        ]}
      />
      <Link to="/incidents" className="text-[length:var(--fs-meta)] text-[color:var(--info)] hover:text-[color:var(--text-primary)]">
        Back to incidents
      </Link>

      <Region state={state} rows={10}>
        {(data) => (
          <div className="space-y-4">
            <Panel
              title={
                <span className="num">{segmentLabel(data.incident.segment_key)}</span>
              }
              subtitle={
                <span className="num">
                  {data.incident.segment_key}
                  {data.incident.affected_scope.length > 1 &&
                    ` covering ${data.incident.affected_scope.length} keys`}
                </span>
              }
              right={
                <div className="flex items-center gap-2">
                  <a
                    href={`/api/ledger/export?ref_id=${encodeURIComponent(data.incident.id)}`}
                    className="btn focus-ring"
                  >
                    Export ledger slice
                  </a>
                  <ConfirmButton
                    label="Close incident"
                    confirmLabel="Close"
                    tone="danger"
                    prompt="Close this incident. Open cases stop receiving actions."
                    disabled={!token || data.incident.closed_at !== null}
                    disabledReason={
                      data.incident.closed_at !== null
                        ? "already closed"
                        : token
                          ? undefined
                          : "enter the token"
                    }
                    onConfirm={async () => {
                      await post(`/api/incidents/${data.incident.id}/close`, {}, token);
                      state.reload();
                    }}
                  />
                </div>
              }
            >
              {/* at risk and recovered are never shown as a ratio, a percentage or a bar. The
                  API computes them over different windows and different populations: at risk is
                  a single detection window, counting orders unpaid at the moment the incident
                  opened, while recovered spans the incident's whole life and is not restricted
                  to those orders. Dividing one by the other produces a number that means
                  nothing, so each carries its scope instead. */}
              <div className="grid gap-3 sm:grid-cols-6">
                <div>
                  <div className="text-[length:var(--fs-meta)] text-[color:var(--text-secondary)]">status</div>
                  <StatusBadge status={data.incident.status} />
                </div>
                <div>
                  <div className="text-[length:var(--fs-meta)] text-[color:var(--text-secondary)]">opened</div>
                  <div className="num text-[length:var(--fs-meta)]">{timestamp(data.incident.opened_at)}</div>
                </div>
                <div>
                  <div className="text-[length:var(--fs-meta)] text-[color:var(--text-secondary)]">closed</div>
                  <div className="num text-[length:var(--fs-meta)]">
                    {data.incident.closed_at ? timestamp(data.incident.closed_at) : "still open"}
                  </div>
                </div>
                <div>
                  <div className="text-[length:var(--fs-meta)] text-[color:var(--text-secondary)]">at risk</div>
                  <div className="num text-[length:var(--fs-meta)] font-semibold">
                    {rupees(data.incident.at_risk_amount)}
                  </div>
                  <div className="text-[length:var(--fs-micro)] text-[color:var(--text-muted)]">
                    detection window, unpaid at open
                  </div>
                </div>
                <div>
                  <div className="text-[length:var(--fs-meta)] text-[color:var(--text-secondary)]">recovered</div>
                  <div
                    className={`num text-[length:var(--fs-meta)] font-semibold ${
                      data.incident.recovered_amount > 0
                        ? "text-[color:var(--success)]"
                        : "text-[color:var(--text-muted)]"
                    }`}
                  >
                    {rupees(data.incident.recovered_amount)}
                  </div>
                  <div className="text-[length:var(--fs-micro)] text-[color:var(--text-muted)]">whole incident, all cases</div>
                </div>
                <div>
                  <div className="text-[length:var(--fs-meta)] text-[color:var(--text-secondary)]">actions</div>
                  <div className="num text-[length:var(--fs-meta)] font-semibold">{count(data.incident.actions)}</div>
                  <div className="text-[length:var(--fs-micro)] text-[color:var(--text-muted)]">
                    on {count(data.incident.cases)} cases, not messages
                  </div>
                </div>
              </div>
            </Panel>

            {data.evidence ? (
              <EvidencePanel evidence={data.evidence} />
            ) : (
              <Panel title="Evidence">
                <Empty>
                  No evidence packet was recorded. The incident was opened but never diagnosed.
                </Empty>
              </Panel>
            )}

            {data.diagnosis ? (
              <DiagnosisPanel diagnosis={data.diagnosis} />
            ) : (
              <Panel title="Diagnosis">
                <Empty>
                  Not diagnosed. With no model configured the agent takes no customer-facing
                  action.
                </Empty>
              </Panel>
            )}

            <PlanPanel plan={data.plan} />
            <CasesPanel cases={data.cases} />

            <Panel
              title="Timeline"
              subtitle="Every ledger entry that names this incident, in sequence order."
            >
              {data.timeline.length === 0 ? (
                <Empty>Nothing written yet.</Empty>
              ) : (
                <div className="max-h-[36rem] overflow-y-auto">
                  <Timeline entries={data.timeline} />
                </div>
              )}
            </Panel>
          </div>
        )}
      </Region>
    </div>
  );
}
