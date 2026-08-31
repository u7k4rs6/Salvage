import { Link } from "react-router-dom";
import { Chip } from "./Chrome";
import { faultForIncident, type RunHeader } from "../../lib/useRunHeader";
import { elapsed, incidentSeverity } from "../../lib/health";
import { causeLabel, count, duration, percent, rupees, timeOnly } from "../../lib/format";
import type { IncidentSummary, Overview, Segment } from "../../lib/types";

/**
 * Active incidents.
 *
 * The strongest section on the page, because it is the only one that names something a person has
 * to do. Every field is read from the incident row or from the segment the detector attributed it
 * to; nothing here is derived from anything the API does not return.
 *
 * Time to detect is the gap between the fault the simulator injected and the window the detector
 * opened on. It is only shown when the run's ledger header carries a fault whose selector matches
 * this incident's key, which means it appears for a simulated world and stays absent for anything
 * else rather than being filled in with an assumption.
 */

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="lbl">{label}</div>
      <div className="fig-md mt-1 truncate">{children}</div>
    </div>
  );
}

function IncidentRow({
  incident,
  segment,
  run,
  now,
  plannerError,
}: {
  incident: IncidentSummary;
  segment: Segment | null;
  run: RunHeader | null;
  now: number;
  plannerError: string | null;
}) {
  const failed = plannerError !== null;
  const severity = incidentSeverity(incident.status, failed);
  const fault = faultForIncident(run, incident);
  const detectedIn = fault ? incident.opened_at - fault.start_ts : null;

  return (
    <article className="px-2 py-4 first:pt-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {run && (
          <span className="chip chip-flat" title={`Scenario ${run.scenario}, seed ${run.seed}`}>
            {run.scenario}
          </span>
        )}
        <h3 className="text-[length:var(--fs-body)] font-medium tracking-[-0.01em]">
          {causeLabel(incident.root_cause).toUpperCase()}
        </h3>
        <span className="mono note truncate">{incident.segment_key}</span>
        <span className="ml-auto flex items-center gap-2">
          {failed && <Chip severity="crit">Planner error</Chip>}
          <Chip severity={severity}>{incident.status}</Chip>
        </span>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3 lg:grid-cols-6">
        <Field label="Opened">
          <span className="mono">{timeOnly(incident.opened_at)}</span>{" "}
          <span className="dim mono text-[length:var(--fs-small)]">{elapsed(incident.opened_at, now)}</span>
        </Field>
        <Field label="Exposure">
          <span className="mono">&#8377;{rupees(incident.at_risk_amount)}</span>
        </Field>
        <Field label="Segment rate">
          {segment ? (
            <span className="mono">
              <span className="crit">{percent(segment.rate)}</span>{" "}
              <span className="dim text-[length:var(--fs-small)]">
                {count(segment.failures)}/{count(segment.attempts)} failed
              </span>
            </span>
          ) : (
            <span className="dim mono text-[length:var(--fs-small)]">below floor this window</span>
          )}
        </Field>
        <Field label="Cases">
          <span className="mono">{count(incident.cases)}</span>{" "}
          <span className="dim mono text-[length:var(--fs-small)]">
            {count(incident.actions)} action{incident.actions === 1 ? "" : "s"}
          </span>
        </Field>
        <Field label="Confidence">
          <span className="mono">
            {incident.confidence === null ? "-" : incident.confidence.toFixed(2)}
          </span>
        </Field>
        <Field label="Time to detect">
          {detectedIn === null ? (
            <span className="dim mono text-[length:var(--fs-small)]">-</span>
          ) : (
            <span className="mono">{duration(detectedIn)}</span>
          )}
        </Field>
      </div>

      {failed && (
        <div className="alert mt-4" role="alert">
          <div className="flex flex-wrap items-baseline gap-x-3">
            <span className="lbl crit">Planner error</span>
            <span className="mono text-[length:var(--fs-small)]">{plannerError}</span>
          </div>
          <p className="note mt-1.5">
            No action was chosen. The executor escalated because planning failed, which is not an
            agent deciding a human should take this one.
          </p>
        </div>
      )}

      <div className="mt-4">
        <Link
          to={`/incidents/${incident.id}`}
          className="link focus-ring lbl lbl-2 inline-flex items-center gap-1.5"
        >
          View incident &rarr;
        </Link>
      </div>
    </article>
  );
}

export function ActiveIncidents({
  data,
  incidents,
  run,
  plannerErrors,
}: {
  data: Overview;
  incidents: IncidentSummary[];
  run: RunHeader | null;
  /** Incident id to the planner error the ledger recorded, when there is one. */
  plannerErrors: Record<string, string>;
}) {
  const byKey = new Map(data.segments.map((segment) => [segment.key, segment]));

  if (incidents.length === 0) {
    return (
      <div className="flex items-center gap-3 px-2 py-3">
        <span className="chip ok">
          <span className="dot" aria-hidden="true" />
          No active incidents
        </span>
        <span className="note">
          Every segment the detector can test is inside its own baseline.
        </span>
      </div>
    );
  }

  return (
    <div className="divide">
      {incidents.map((incident) => (
        <IncidentRow
          key={incident.id}
          incident={incident}
          segment={byKey.get(incident.segment_key) ?? null}
          run={run}
          now={data.now}
          plannerError={plannerErrors[incident.id] ?? null}
        />
      ))}
    </div>
  );
}
