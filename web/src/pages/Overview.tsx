import { useEffect, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useApi, type ApiState } from "../lib/useApi";
import { useStream } from "../lib/useStream";
import { Empty, ErrorPanel, Loading } from "../components/overview/States";
import { Decoded } from "../components/overview/Decoded";
import { Figure } from "../components/overview/Figure";
import { Volume } from "../components/overview/Volume";
import { SegmentMatrix } from "../components/overview/SegmentMatrix";
import { Lifecycle } from "../components/overview/Lifecycle";
import { Activity } from "../components/overview/Activity";
import {
  causeLabel,
  count,
  isSyntheticIncident,
  percent,
  rupees,
  segmentLabel,
  timeOnly,
} from "../lib/format";
import type { IncidentDetail, LedgerPage, Overview as OverviewData } from "../lib/types";
import "./overview.css";

/**
 * The Overview.
 *
 * Dark editorial: one continuous surface divided by full-bleed hairlines, not a grid of cards.
 * Five numbered regions, their ordinals set in the left margin in the accent, running 01 STATUS,
 * 02 PAYMENT HEALTH, 03 CURRENT INCIDENT, 04 LIFECYCLE, 05 ACTIVITY. The jump from a 104px stat
 * to a 10px microlabel is the whole typographic idea, and the microlabel is not decoration: it
 * names the population a number covers.
 *
 * Three rules the layout exists to keep.
 *
 * Every number names the population and the window it covers, because the four headline figures
 * do not share one. At-risk and recovered are never divided by each other: they cover different
 * windows over different populations, and the ratio is meaningless, so the note under the stat
 * row says so and points at `/api/results`, where numerator and denominator do share a set. And
 * a planner failure is drawn as an error, never as an escalation somebody chose, because the two
 * arrive at the same place in the state machine and mean opposite things.
 *
 * Motion is rationed to one effect. A value that changes state decodes through random glyphs of
 * its own character class over 450ms; everything else is a 150ms hover. Nothing decodes on first
 * paint. See lib/useScramble.ts.
 */

// -- furniture -------------------------------------------------------------

function Region({
  index,
  name,
  children,
}: {
  index: string;
  name: string;
  children: ReactNode;
}) {
  return (
    <section className="region" aria-labelledby={`region-${index}`}>
      <div className="region-inner">
        <div className="rail">
          <span className="rail-no">{index}</span>
          <span className="rail-name" id={`region-${index}`}>
            {name}
          </span>
        </div>
        <div className="min-w-0">{children}</div>
      </div>
    </section>
  );
}

/**
 * The dark surface reaches the top bar and the left nav, which belong to every page. Rather than
 * restyle six pages nobody asked me to touch, the attribute lives only while this page is
 * mounted and every chrome rule in overview.css is gated on it.
 */
function useDarkChrome() {
  useEffect(() => {
    document.documentElement.setAttribute("data-surface", "dark");
    return () => document.documentElement.removeAttribute("data-surface");
  }, []);
}

function Wordmark() {
  return (
    <div>
      <h1 className="display" style={{ fontSize: "clamp(40px, 5.2vw, 68px)" }}>
        Salvage
      </h1>
      <p className="microlabel mt-4">Payment recovery infrastructure</p>
      <p className="body mt-5 max-w-sm">
        Detects failure clusters in a merchant&rsquo;s payment traffic, diagnoses the cause from
        evidence, and acts inside hard limits or hands the incident to a human.
      </p>
    </div>
  );
}

// -- 01 status -------------------------------------------------------------

function Status({ data }: { data: OverviewData }) {
  const open = data.incidents.filter((incident) => !isSyntheticIncident(incident.id));
  const degraded = data.stats.success_rate !== null && data.stats.success_rate < 0.85;

  return (
    <div className="stack">
      <div className="grid grid-cols-1 gap-10 lg:grid-cols-12 lg:items-end">
        <div className="lg:col-span-6">
          <Wordmark />
        </div>
        <div className="lg:col-span-6">
          <Figure
            size="hero"
            value={percent(data.stats.success_rate)}
            label="Merchant success rate"
            tone={degraded ? "incident" : "ink"}
            scope={`Last hour on the ${data.clock} clock, ${count(data.stats.attempts_last_hour)} attempts, window ${timeOnly(data.window.start)} to ${timeOnly(data.window.end)}.`}
          />
        </div>
      </div>

      <div className="stat-row" style={{ borderTop: "1px solid var(--hair)", paddingTop: 28 }}>
        <div className="stat-cell">
          <Figure
            value={rupees(data.stats.at_risk_amount)}
            prefix="&#8377;"
            label="Exposure"
            tone={data.stats.at_risk_amount > 0 ? "incident" : "ink"}
            scope="Open incidents, each measured over its own detection window."
          />
        </div>
        <div className="stat-cell">
          <Figure
            value={rupees(data.stats.recovered_amount)}
            prefix="&#8377;"
            label="Recovered"
            tone={data.stats.recovered_amount > 0 ? "recovered" : "muted"}
            scope="All time, link and steer routes only, excludes organic recovery."
          />
        </div>
        <div className="stat-cell">
          <Figure
            value={String(open.length).padStart(2, "0")}
            label="Active incidents"
            tone={open.length > 0 ? "incident" : "ink"}
            scope="Open now, synthetic baseline rows excluded."
          />
        </div>
        <div className="stat-cell">
          <Figure
            value={count(data.stats.attempts_last_hour)}
            label="Attempts"
            scope={`Last hour, ending ${timeOnly(data.window.end)}.`}
          />
        </div>
      </div>

      <p className="body-sm max-w-3xl">
        Exposure and recovered are not two ends of one number. Exposure is a single detection
        window counting orders unpaid when the incident opened; recovered spans every
        incident&rsquo;s whole life over a population that is not the same set. Dividing them
        produces nothing. The measured recovery rate, where numerator and denominator do share a
        set, is on{" "}
        <Link
          to="/results"
          className="focus-ring underline underline-offset-4"
          style={{ color: "var(--text)", textDecorationColor: "var(--text-3)" }}
        >
          Results
        </Link>
        .
      </p>

      <div style={{ borderTop: "1px solid var(--hair)", paddingTop: 28 }}>
        <Volume data={data} />
      </div>
    </div>
  );
}

// -- 03 current incident ---------------------------------------------------

/**
 * The planner can fail, and when it does the executor still escalates. That path lands in the
 * same state as a considered handover and means the opposite thing, so it is read out of the
 * ledger and drawn as an error rather than as a decision.
 */
function plannerError(detail: IncidentDetail): string | null {
  const planEntry = detail.timeline.find((entry) => entry.kind === "decide.plan");
  const fromLedger = planEntry?.payload?.planner_error;
  if (typeof fromLedger === "string" && fromLedger.length > 0) return fromLedger;
  const rationale = detail.plan?.rationale ?? "";
  return rationale.startsWith("planner failed") ? rationale : null;
}

function IncidentFocus({ detail }: { detail: ApiState<IncidentDetail> }) {
  if (detail.error) return <ErrorPanel error={detail.error} retry={detail.reload} />;
  if (!detail.data) return <Loading rows={4} label="Loading the open incident" />;

  const { incident, diagnosis, plan } = detail.data;
  const proposed = plan.proposed[0];
  const failure = plannerError(detail.data);

  return (
    <div className="stack">
      <div>
        <div className="flex flex-wrap items-baseline gap-x-5 gap-y-2">
          <Decoded
            value={incident.id}
            className="mono"
            style={{ fontSize: 12, color: "var(--text-3)" }}
          />
          <span
            className="microlabel"
            style={{ color: incident.escalated ? "var(--pending)" : "var(--incident)" }}
          >
            {incident.status}
          </span>
        </div>

        <h2 className="display heading mt-4" style={{ fontSize: "clamp(32px, 4.6vw, 56px)" }}>
          <Decoded value={causeLabel(incident.root_cause)} />
        </h2>
      </div>

      <div className="grid grid-cols-2 gap-x-10 gap-y-7 sm:grid-cols-4">
        <div>
          <div className="microlabel">Attribution</div>
          <div className="mono mt-2" style={{ fontSize: 13 }}>
            {segmentLabel(incident.segment_key)}
          </div>
          <div className="mono scope mt-1">{incident.segment_key}</div>
        </div>
        <div>
          <div className="microlabel">Confidence</div>
          <div className="display mt-2" style={{ fontSize: 20 }}>
            <Decoded value={incident.confidence === null ? "-" : incident.confidence.toFixed(2)} />
          </div>
          <div className="scope mt-1">
            {diagnosis?.agreed ? "rules and model agreed" : "rules and model disagreed"}
          </div>
        </div>
        <div>
          <div className="microlabel">Exposure</div>
          <div className="display mt-2" style={{ fontSize: 20 }}>
            &#8377;{rupees(incident.at_risk_amount)}
          </div>
          <div className="scope mt-1">detection window</div>
        </div>
        <div>
          <div className="microlabel">Cases</div>
          <div className="display mt-2" style={{ fontSize: 20 }}>
            {count(incident.cases)}
            <span style={{ color: "var(--text-3)" }}> / {count(incident.actions)}</span>
          </div>
          <div className="scope mt-1">cases and actions, never messages</div>
        </div>
      </div>

      {/* A planner failure and a considered handover both end at ESCALATE_HUMAN. Only one of them
          is a decision, so they are never drawn the same way. */}
      {failure !== null ? (
        <div className="error-block" role="alert">
          <div className="microlabel" style={{ color: "var(--incident)" }}>
            Planner error
          </div>
          <div className="mono mt-2" style={{ fontSize: 12, color: "var(--text)" }}>
            {failure}
          </div>
          <p className="body-sm mt-3 max-w-2xl">
            No action was chosen. The executor escalated because planning failed, which is not the
            same as an agent deciding a human should take this one, and the two are not counted
            together anywhere.
          </p>
        </div>
      ) : (
        proposed && (
          <div>
            <div className="microlabel">Proposed action</div>
            <div className="mono mt-2" style={{ fontSize: 13 }}>
              {String(proposed.type)}
              <span style={{ color: "var(--text-3)" }}> scope {String(proposed.scope)}</span>
            </div>
            {plan.rationale && <p className="body-sm mt-2 max-w-2xl">{plan.rationale}</p>}
          </div>
        )
      )}

      <div>
        <Link
          to={`/incidents/${incident.id}`}
          className="focus-ring microlabel microlabel-ink lift inline-block"
        >
          Evidence, diagnosis and gates &rarr;
        </Link>
      </div>
    </div>
  );
}

// -- page ------------------------------------------------------------------

export default function OverviewPage() {
  useDarkChrome();
  const state = useApi<OverviewData>("/api/overview");
  const ledger = useApi<LedgerPage>("/api/ledger?limit=8");

  useStream(
    [
      "attempt",
      "incident.opened",
      "incident.updated",
      "incident.closed",
      "action.executed",
      "escalation.opened",
      "ledger.appended",
      "sim.finished",
    ],
    () => {
      state.reload();
      ledger.reload();
    },
  );

  if (state.error) {
    return (
      <div className="ov">
        <Region index="01" name="Status">
          <ErrorPanel error={state.error} retry={state.reload} />
        </Region>
      </div>
    );
  }

  if (state.loading && state.data === null) {
    return (
      <div className="ov">
        <Region index="01" name="Status">
          <Loading rows={8} label="Loading the overview" />
        </Region>
      </div>
    );
  }

  if (state.data === null || state.data.segments.length === 0) {
    return (
      <div className="ov">
        <Region index="01" name="Status">
          <Wordmark />
          <div className="mt-10" style={{ borderTop: "1px solid var(--hair)" }}>
            <Empty
              action={
                <Link to="/runner" className="focus-ring microlabel microlabel-ink lift">
                  Go to Scenario Runner &rarr;
                </Link>
              }
            >
              No attempts yet. Nothing has been measured, so there is nothing to deviate from.
            </Empty>
          </div>
        </Region>
      </div>
    );
  }

  const data = state.data;
  const focus = data.incidents.find((incident) => !isSyntheticIncident(incident.id));
  return <OverviewBody data={data} focusId={focus?.id ?? null} ledger={ledger} />;
}

/**
 * Split from the page so the focused incident's detail can be fetched with a hook without
 * putting a conditional hook above the loading and empty returns.
 */
function OverviewBody({
  data,
  focusId,
  ledger,
}: {
  data: OverviewData;
  focusId: string | null;
  ledger: ApiState<LedgerPage>;
}) {
  const detail = useApi<IncidentDetail>(focusId ? `/api/incidents/${focusId}` : null, [focusId]);
  useStream(["incident.updated", "action.executed", "escalation.opened"], () => detail.reload());

  return (
    <div className="ov">
      <Region index="01" name="Status">
        <Status data={data} />
      </Region>

      <Region index="02" name="Payment health">
        <SegmentMatrix segments={data.segments} />
      </Region>

      <Region index="03" name="Current incident">
        {focusId ? (
          <IncidentFocus detail={detail} />
        ) : (
          <div>
            <h2 className="display heading">Nothing open</h2>
            <p className="body mt-4 max-w-xl">
              Every segment the detector could test is inside its own baseline. The lane above
              shows which ones it could not.
            </p>
          </div>
        )}
      </Region>

      <Region index="04" name="Lifecycle">
        {focusId && detail.data ? (
          <Lifecycle data={detail.data} />
        ) : focusId ? (
          <Loading rows={2} label="Loading the lifecycle" />
        ) : (
          <p className="body max-w-xl">
            The pipeline runs per incident. With nothing open there is no walk to draw.
          </p>
        )}
      </Region>

      <Region index="05" name="Activity">
        {ledger.error ? (
          <ErrorPanel error={ledger.error} retry={ledger.reload} />
        ) : ledger.data ? (
          <Activity page={ledger.data} clock={data.clock} />
        ) : (
          <Loading rows={5} label="Loading activity" />
        )}
      </Region>
    </div>
  );
}
