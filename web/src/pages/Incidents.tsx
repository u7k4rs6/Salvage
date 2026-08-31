import { useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../lib/useApi";
import { useStream } from "../lib/useStream";
import { Badge, Empty, Panel, Region, StatusBadge, Table } from "../components/primitives";
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
        <label className="text-[length:var(--fs-small)] text-[color:var(--fg-2)]">
          status{" "}
          <select
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setOffset(0);
            }}
            className="border border-[color:var(--line-2)] px-2 py-1 text-[length:var(--fs-small)]"
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
              <Table
                columns={[
                  "opened",
                  "segment",
                  "root cause",
                  "confidence",
                  "status",
                  "at risk",
                  "recovered",
                  "actions",
                  "escalation",
                ]}
                align={[
                  "left",
                  "left",
                  "left",
                  "right",
                  "left",
                  "right",
                  "right",
                  "right",
                  "left",
                ]}
              >
                {data.incidents.map((incident) => (
                  <tr key={incident.id} className="border-b border-[color:var(--line)] hover:bg-[color:var(--panel-2)]">
                    <td className="cell-pad num whitespace-nowrap text-[length:var(--fs-small)]">
                      <Link
                        to={`/incidents/${incident.id}`}
                        className="text-[color:var(--info)] hover:text-[color:var(--fg)]"
                      >
                        {timestamp(incident.opened_at)}
                      </Link>
                    </td>
                    <td className="cell-pad num">{segmentLabel(incident.segment_key)}</td>
                    <td className="cell-pad">
                      {isSyntheticIncident(incident.id) ? (
                        <span className="text-[color:var(--fg-3)]">synthetic (baseline policy)</span>
                      ) : (
                        causeLabel(incident.root_cause)
                      )}
                    </td>
                    <td className="cell-pad num text-right">
                      {incident.confidence === null ? "-" : incident.confidence.toFixed(2)}
                    </td>
                    <td className="cell-pad">
                      <StatusBadge status={incident.status} />
                    </td>
                    <td className="cell-pad num text-right">{rupees(incident.at_risk_amount)}</td>
                    {/* Green says money came back. Zero says none did, so it is not green: a
                        recovered figure of 0.00 in the success colour reads as good news about a
                        number that is not good news. */}
                    <td
                      className={`cell-pad num text-right ${
                        incident.recovered_amount > 0
                          ? "text-[color:var(--ok)]"
                          : "text-[color:var(--fg-3)]"
                      }`}
                    >
                      {rupees(incident.recovered_amount)}
                    </td>
                    <td className="cell-pad num text-right">{count(incident.actions)}</td>
                    <td className="cell-pad">
                      {incident.escalated ? <Badge tone="amber">escalated</Badge> : ""}
                    </td>
                  </tr>
                ))}
              </Table>
              <div className="mt-3 flex items-center gap-3 text-[length:var(--fs-small)] text-[color:var(--fg-2)]">
                <span className="num">
                  {offset + 1} to {Math.min(offset + data.limit, data.total)} of {data.total}
                </span>
                <button
                  type="button"
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - data.limit))}
                  className="border border-[color:var(--line-2)] px-2 py-1 disabled:opacity-40"
                >
                  Previous
                </button>
                <button
                  type="button"
                  disabled={offset + data.limit >= data.total}
                  onClick={() => setOffset(offset + data.limit)}
                  className="border border-[color:var(--line-2)] px-2 py-1 disabled:opacity-40"
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
