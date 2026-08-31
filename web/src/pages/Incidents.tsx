import { useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../lib/useApi";
import { useStream } from "../lib/useStream";
import {
  Badge,
  Cell,
  Empty,
  Panel,
  Region,
  StatusBadge,
  Table,
  type Column,
} from "../components/primitives";
import {
  causeLabel,
  count,
  isSyntheticIncident,
  rupees,
  segmentLabel,
  timestamp,
} from "../lib/format";
import type { IncidentList } from "../lib/types";
import { PageIntro } from "../components/PageIntro";

const STATUSES = ["all", "open", "escalated", "paused", "recovering", "closed"];

/**
 * The column model for the incident list.
 *
 * Money and counts are numeric, so they share a right edge and tabular figures; the status and the
 * escalation flag are compact states, so they centre; everything else is text. Declared here and
 * read back by every cell, so a header can never sit over values aligned the other way.
 */
const INCIDENT_COLUMNS: Column[] = [
  // Shares, not pixels, so the row spans whatever the panel gives it. The two nowrap columns, the
  // timestamp and the escalation badge, get enough of the share that they cannot bleed into their
  // neighbour, and `minWidth` on the table below is the floor where that stays true.
  { key: "opened", label: "Opened", align: "text", width: "17%" },
  { key: "segment", label: "Segment", align: "text", width: "14%" },
  { key: "cause", label: "Root cause", align: "text", width: "12%" },
  { key: "confidence", label: "Confidence", align: "num", width: "9%" },
  { key: "status", label: "Status", align: "status", width: "10%" },
  { key: "at_risk", label: "At risk", align: "num", width: "11%" },
  { key: "recovered", label: "Recovered", align: "num", width: "11%" },
  { key: "actions", label: "Actions", align: "num", width: "7%" },
  { key: "escalation", label: "Escalation", align: "status", width: "9%" },
];

export default function IncidentsPage() {
  const [status, setStatus] = useState("all");
  const [offset, setOffset] = useState(0);
  const query = `/api/incidents?limit=50&offset=${offset}${status === "all" ? "" : `&status=${status}`}`;
  const state = useApi<IncidentList>(query);
  useStream(["incident.opened", "incident.updated", "incident.closed"], () => state.reload());

  return (
    <>
      <PageIntro
        title="Incidents"
        what="Every incident the detector has opened, newest first. An incident is one slice of traffic failing far more than that same slice normally does."
        use="Click a row to open the evidence, the diagnosis, and every action the agent took or refused for that incident."
        shows={[
          ["Segment", "the slice of traffic that is failing, such as one card BIN, one UPI handle, or the whole merchant"],
          ["Root cause", "what the diagnosis settled on after a rules classifier and a language model both read the same evidence"],
          ["Confidence", "how sure that diagnosis is. Below 0.6 the agent may not do anything to a customer"],
          ["At risk", "money in orders that failed inside this incident and were still unpaid when it opened"],
          ["Recovered", "money from orders the agent brought back, by payment link or by steering the shopper to another method"],
          ["Actions", "how many things the agent did or refused to do. A refusal is recorded as fully as an action"],
        ]}
        caveat="At risk and recovered are never divided by one another. They are measured over different populations and different windows, so a ratio of the two would not mean anything."
      />
    <Panel
      title="Incidents"
      subtitle="Every incident the detector opened, newest first."
      right={
        <label className="text-[length:var(--fs-meta)] text-[color:var(--text-secondary)]">
          status{" "}
          <select
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setOffset(0);
            }}
            className="btn focus-ring"
          >
            {STATUSES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
      }
    >
      <Region state={state} rows={8}>
        {(data) =>
          data.incidents.length === 0 ? (
            <Empty>
              No incidents with this status. The detector opens one when a segment stays outside
              its baseline for two consecutive windows.
            </Empty>
          ) : (
            <>
              <Table columns={INCIDENT_COLUMNS} minWidth="70rem">
                {data.incidents.map((incident) => (
                  <tr key={incident.id}>
                    <Cell column="opened">
                      <Link
                        to={`/incidents/${incident.id}`}
                        className="dt-mono whitespace-nowrap text-[color:var(--accent)] hover:text-[color:var(--text-primary)]"
                      >
                        {timestamp(incident.opened_at)}
                      </Link>
                    </Cell>
                    <Cell column="segment">
                      <span className="dt-mono">{segmentLabel(incident.segment_key)}</span>
                    </Cell>
                    <Cell column="cause">
                      {isSyntheticIncident(incident.id) ? (
                        <span className="text-[color:var(--text-muted)]">
                          synthetic (baseline policy)
                        </span>
                      ) : (
                        causeLabel(incident.root_cause)
                      )}
                    </Cell>
                    <Cell column="confidence">
                      {incident.confidence === null ? "-" : incident.confidence.toFixed(2)}
                    </Cell>
                    <Cell column="status">
                      <StatusBadge status={incident.status} />
                    </Cell>
                    <Cell column="at_risk">{rupees(incident.at_risk_amount)}</Cell>
                    {/* Green says money came back. Zero says none did, so a recovered figure of
                        0.00 in the success colour reads as good news about a number that is not. */}
                    <Cell
                      column="recovered"
                      className={
                        incident.recovered_amount > 0
                          ? "text-[color:var(--success)]"
                          : "text-[color:var(--text-muted)]"
                      }
                    >
                      {rupees(incident.recovered_amount)}
                    </Cell>
                    <Cell column="actions">{count(incident.actions)}</Cell>
                    <Cell column="escalation">
                      {incident.escalated ? <Badge tone="warning">escalated</Badge> : null}
                    </Cell>
                  </tr>
                ))}
              </Table>
              <div className="mt-3 flex items-center gap-3 text-[length:var(--fs-meta)] text-[color:var(--text-secondary)]">
                <span className="num">
                  {offset + 1} to {Math.min(offset + data.limit, data.total)} of {data.total}
                </span>
                <button
                  type="button"
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - data.limit))}
                  className="btn btn-sm focus-ring"
                >
                  Previous
                </button>
                <button
                  type="button"
                  disabled={offset + data.limit >= data.total}
                  onClick={() => setOffset(offset + data.limit)}
                  className="btn btn-sm focus-ring"
                >
                  Next
                </button>
              </div>
            </>
          )
        }
      </Region>
    </Panel>
    </>
  );
}
