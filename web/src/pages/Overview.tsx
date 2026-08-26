import { Link } from "react-router-dom";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useApi, type ApiState } from "../lib/useApi";
import { useStream } from "../lib/useStream";
import { Empty, ErrorPanel, Loading } from "../components/primitives";
import { Figure } from "../components/overview/Figure";
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
 * Composition rather than a grid of widgets: a masthead that says what this is, one metric large
 * enough to read across a room, a band of secondary figures each carrying its own scope, the
 * incident that is open right now with the pipeline it has walked, then the two dense regions,
 * payment health and the ledger.
 *
 * Two rules the layout exists to keep. Every number names the population and window it covers,
 * because the four headline figures do not share one. And at-risk and recovered are never divided
 * by each other: they cover different windows over different populations, and the ratio is
 * meaningless. `/api/results` has `at_risk_recovery_rate`, where numerator and denominator do
 * share a set, and the Results page is where it belongs.
 */

function Masthead({ data }: { data: OverviewData }) {
  return (
    <div className="grid grid-cols-1 gap-8 lg:grid-cols-12 lg:items-end">
      <div className="lg:col-span-7">
        <h1 className="display text-[clamp(3rem,7.5vw,6.5rem)]">Salvage</h1>
        <p className="label mt-3 text-[11px] tracking-[0.22em]">
          Payment recovery infrastructure
        </p>
        <p className="mt-4 max-w-md text-[13px] leading-relaxed text-[color:var(--ink-2)]">
          Detects failure clusters in a merchant&rsquo;s payment traffic, diagnoses the cause from
          evidence, and acts inside hard limits or hands the incident to a human.
        </p>
      </div>

      <div className="lg:col-span-5">
        <Figure
          size="xl"
          value={percent(data.stats.success_rate)}
          label="Merchant success rate"
          scope={`last hour on the ${data.clock} clock, ${count(data.stats.attempts_last_hour)} attempts`}
          tone={
            data.stats.success_rate !== null && data.stats.success_rate < 0.85 ? "incident" : "ink"
          }
        />
        <p className="num mt-4 text-[11px] text-[color:var(--ink-3)]">
          window {timeOnly(data.window.start)} to {timeOnly(data.window.end)}
        </p>
      </div>
    </div>
  );
}

function FigureBand({ data }: { data: OverviewData }) {
  const openIncidents = data.incidents.filter((incident) => !isSyntheticIncident(incident.id));

  return (
    <div>
      <div className="grid grid-cols-2 gap-x-8 gap-y-8 lg:grid-cols-4">
        <div className="lg:border-r lg:border-[color:var(--line)] lg:pr-8">
          <Figure
            value={rupees(data.stats.at_risk_amount)}
            prefix="&#8377;"
            label="Exposure"
            scope="open incidents, each measured over its own detection window"
            tone={data.stats.at_risk_amount > 0 ? "incident" : "ink"}
          />
        </div>
        <div className="lg:border-r lg:border-[color:var(--line)] lg:pr-8">
          <Figure
            value={rupees(data.stats.recovered_amount)}
            prefix="&#8377;"
            label="Recovered"
            scope="all time, link and steer routes only, excludes organic recovery"
            tone={data.stats.recovered_amount > 0 ? "recover" : "ink"}
          />
        </div>
        <div className="lg:border-r lg:border-[color:var(--line)] lg:pr-8">
          <Figure
            value={String(openIncidents.length).padStart(2, "0")}
            label="Active incidents"
            scope="open now, synthetic baseline rows excluded"
            tone={openIncidents.length > 0 ? "incident" : "ink"}
          />
        </div>
        <div>
          <Figure
            value={count(data.stats.attempts_last_hour)}
            label="Attempts"
            scope={`last hour, ending ${timeOnly(data.window.end)}`}
          />
        </div>
      </div>
      <p className="mt-6 max-w-2xl text-[12px] leading-snug text-[color:var(--ink-2)]">
        Exposure and recovered are not two ends of one number. Exposure is a single detection
        window counting orders unpaid when the incident opened; recovered spans every incident&rsquo;s
        whole life over a population that is not the same set. Dividing them produces nothing.
        The measured recovery rate, where numerator and denominator do share a set, is on{" "}
        <Link to="/results" className="focus-ring underline underline-offset-2">
          Results
        </Link>
        .
      </p>
    </div>
  );
}

function IncidentFocus({ detail }: { detail: ApiState<IncidentDetail> }) {
  if (detail.error) return <ErrorPanel error={detail.error} retry={detail.reload} />;
  if (!detail.data) return <Loading rows={4} label="Loading the open incident" />;

  const { incident, diagnosis, plan } = detail.data;
  const proposed = plan.proposed[0];

  return (
    <div>
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <span className="num text-[12px] text-[color:var(--ink-3)]">{incident.id}</span>
        <span
          className="label"
          style={{ color: incident.escalated ? "var(--escalate)" : "var(--incident)" }}
        >
          {incident.status}
        </span>
      </div>

      <h2 className="display mt-2 text-[clamp(2rem,4vw,3.25rem)]">
        {causeLabel(incident.root_cause)}
      </h2>

      <div className="mt-5 grid grid-cols-2 gap-x-8 gap-y-5 sm:grid-cols-4">
        <div>
          <div className="label">Attribution</div>
          <div className="num mt-1 text-[13px]">{segmentLabel(incident.segment_key)}</div>
          <div className="num text-[10.5px] text-[color:var(--ink-3)]">{incident.segment_key}</div>
        </div>
        <div>
          <div className="label">Confidence</div>
          <div className="num mt-1 text-[13px]">
            {incident.confidence === null ? "-" : incident.confidence.toFixed(2)}
          </div>
          <div className="text-[10.5px] text-[color:var(--ink-3)]">
            {diagnosis?.agreed ? "rules and model agreed" : "rules and model disagreed"}
          </div>
        </div>
        <div>
          <div className="label">Exposure</div>
          <div className="num mt-1 text-[13px]">&#8377;{rupees(incident.at_risk_amount)}</div>
          <div className="text-[10.5px] text-[color:var(--ink-3)]">detection window</div>
        </div>
        <div>
          <div className="label">Cases</div>
          <div className="num mt-1 text-[13px]">
            {count(incident.cases)}{" "}
            <span className="text-[color:var(--ink-3)]">/ {count(incident.actions)} actions</span>
          </div>
          <div className="text-[10.5px] text-[color:var(--ink-3)]">actions, not messages</div>
        </div>
      </div>

      {proposed && (
        <div className="rule mt-5 pt-4">
          <div className="label">Proposed action</div>
          <div className="num mt-1 text-[13px]">
            {String(proposed.type)}{" "}
            <span className="text-[color:var(--ink-3)]">scope {String(proposed.scope)}</span>
          </div>
          {plan.rationale && (
            <p className="mt-1 max-w-2xl text-[11.5px] leading-snug text-[color:var(--ink-2)]">
              {plan.rationale}
            </p>
          )}
        </div>
      )}

      <Link
        to={`/incidents/${incident.id}`}
        className="focus-ring label label-ink mt-5 inline-block hover:text-[color:var(--ink)]"
      >
        Evidence, diagnosis and gates &rarr;
      </Link>
    </div>
  );
}

function Volume({ data }: { data: OverviewData }) {
  return (
    <div>
      <h2 className="display text-[clamp(1.25rem,1.8vw,1.6rem)]">Volume and failures</h2>
      <p className="label mt-1.5 normal-case tracking-normal text-[11px]">
        Last 24 sim hours, 15-minute buckets, bounded at the current window
      </p>
      <div className="mt-4 h-52">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data.series} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
            <XAxis
              dataKey="t"
              tickFormatter={timeOnly}
              tick={{ fontSize: 10, fill: "#a1a1aa" }}
              stroke="#e4e4e7"
              minTickGap={56}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 10, fill: "#a1a1aa" }}
              stroke="#e4e4e7"
              width={32}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              labelFormatter={(value) => timeOnly(Number(value))}
              contentStyle={{ fontSize: 11, border: "1px solid #d4d4d8", borderRadius: 0 }}
            />
            <Area
              type="monotone"
              dataKey="attempts"
              stroke="#a1a1aa"
              fill="#f4f4f5"
              strokeWidth={1}
              name="attempts"
            />
            <Area
              type="monotone"
              dataKey="failures"
              stroke="#dc2626"
              fill="#fee2e2"
              strokeWidth={1.5}
              name="failures"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export default function OverviewPage() {
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
      <div className="ov band">
        <ErrorPanel error={state.error} retry={state.reload} />
      </div>
    );
  }
  if (state.loading && state.data === null) {
    return (
      <div className="ov band">
        <Loading rows={8} label="Loading the overview" />
      </div>
    );
  }
  if (state.data === null || state.data.segments.length === 0) {
    return (
      <div className="ov band">
        <h1 className="display text-[clamp(3rem,7.5vw,6.5rem)]">Salvage</h1>
        <p className="label mt-3 text-[11px] tracking-[0.22em]">
          Payment recovery infrastructure
        </p>
        <div className="rule-strong mt-8 pt-8">
          <Empty
            action={
              <Link to="/runner" className="focus-ring label label-ink hover:text-[color:var(--ink)]">
                Go to Scenario Runner &rarr;
              </Link>
            }
          >
            No attempts yet. Run a scenario.
          </Empty>
        </div>
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
      <section className="band">
        <Masthead data={data} />
      </section>

      <section className="band rule-strong">
        <FigureBand data={data} />
      </section>

      <section className="band rule">
        <div className="grid grid-cols-1 gap-10 lg:grid-cols-12">
          <div className="lg:col-span-7">
            <h2 className="label mb-4">Current incident</h2>
            {focusId ? (
              <IncidentFocus detail={detail} />
            ) : (
              <p className="text-[13px] text-[color:var(--ink-2)]">
                Nothing open. Every segment is inside its baseline.
              </p>
            )}
          </div>
          <div className="lg:col-span-5">
            <Volume data={data} />
          </div>
        </div>
      </section>

      {focusId && detail.data && (
        <section className="band rule">
          <h2 className="label mb-4">Lifecycle</h2>
          <Lifecycle data={detail.data} />
        </section>
      )}

      <section className="band rule">
        <div className="grid grid-cols-1 gap-10 lg:grid-cols-12">
          <div className="lg:col-span-8">
            <SegmentMatrix segments={data.segments} />
          </div>
          <div className="lg:col-span-4">
            {ledger.error ? (
              <ErrorPanel error={ledger.error} retry={ledger.reload} />
            ) : ledger.data ? (
              <Activity page={ledger.data} clock={data.clock} />
            ) : (
              <Loading rows={5} label="Loading activity" />
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
