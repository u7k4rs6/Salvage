import { useEffect } from "react";
import { Link } from "react-router-dom";
import { useApi, type ApiState } from "../lib/useApi";
import { useStream } from "../lib/useStream";
import { useRunHeader } from "../lib/useRunHeader";
import { plannerErrorOf, realIncidents } from "../lib/health";
import { Chip, Section } from "../components/overview/Chrome";
import { Empty, ErrorPanel, Loading } from "../components/overview/States";
import { StatusStrip } from "../components/overview/StatusStrip";
import { ActiveIncidents } from "../components/overview/ActiveIncidents";
import { PaymentHealth } from "../components/overview/PaymentHealth";
import { TrafficTimeline } from "../components/overview/TrafficTimeline";
import { Lifecycle } from "../components/overview/Lifecycle";
import { Activity } from "../components/overview/Activity";
import { causeLabel, timeOnly } from "../lib/format";
import type { IncidentDetail, LedgerPage, Overview as OverviewData } from "../lib/types";
import "./overview.css";

/**
 * The Overview: an operational control plane, read top to bottom in severity order.
 *
 * Current state, then what is broken, then where, then when it started, then what the agent did
 * about it. Sections are separated by a rule rather than boxed into cards, because the page is one
 * surface and a reader scanning it during an incident should not have to re-orient at every panel
 * edge.
 *
 * Three rules the layout keeps.
 *
 * Colour is scarce and means one thing. Red is an active failure or a refusal, amber is degraded
 * or waiting on a human, blue is informational, green is healthy. The large figures are plain: a
 * number being important is not a severity, so the colour sits on deltas and status chips where it
 * carries information.
 *
 * Numbers name their window. The headline success rate is the last 60 minutes; the deviation
 * beside it is the merchant-wide key in the detector's own 15 minute window against its seven-day
 * baseline. They are shown as two labelled facts rather than subtracted into one, because that
 * subtraction spans two populations. Exposure and recovered are never divided by each other, and
 * the reason is behind the methodology disclosure rather than set as prose in the middle of the
 * metrics.
 *
 * A planner failure is read out of the ledger's `decide.plan` payload and marked as an error, not
 * as a handover somebody chose. Both land at ESCALATE_HUMAN and they mean opposite things.
 */

/**
 * The dark surface reaches the top bar and the left nav, which belong to every page. Rather than
 * restyle six pages nobody asked for, the attribute lives only while this page is mounted and
 * every chrome rule in overview.css is gated on it.
 */
function useOpsChrome() {
  useEffect(() => {
    document.documentElement.setAttribute("data-surface", "ops");
    return () => document.documentElement.removeAttribute("data-surface");
  }, []);
}

export default function OverviewPage() {
  useOpsChrome();
  const state = useApi<OverviewData>("/api/overview");
  const ledger = useApi<LedgerPage>("/api/ledger?limit=10");

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
        <Section title="Status">
          <ErrorPanel error={state.error} retry={state.reload} />
        </Section>
      </div>
    );
  }

  if (state.loading && state.data === null) {
    return (
      <div className="ov">
        <Section title="Status">
          <Loading rows={4} label="Loading the overview" />
        </Section>
      </div>
    );
  }

  if (state.data === null || state.data.segments.length === 0) {
    return (
      <div className="ov">
        <Section title="Status">
          <Empty
            action={
              <Link to="/runner" className="link focus-ring lbl lbl-2">
                Scenario Runner &rarr;
              </Link>
            }
          >
            No attempts measured. Nothing has been observed, so there is no baseline to deviate
            from.
          </Empty>
        </Section>
      </div>
    );
  }

  return <OverviewBody data={state.data} ledger={ledger} />;
}

/**
 * Split from the page so the focused incident's detail can be fetched with a hook without putting
 * a conditional hook above the loading and empty returns.
 */
function OverviewBody({
  data,
  ledger,
}: {
  data: OverviewData;
  ledger: ApiState<LedgerPage>;
}) {
  const run = useRunHeader();
  const incidents = realIncidents(data.incidents);
  const focusId = incidents[0]?.id ?? null;

  const detail = useApi<IncidentDetail>(focusId ? `/api/incidents/${focusId}` : null, [focusId]);
  useStream(["incident.updated", "action.executed", "escalation.opened"], () => detail.reload());

  // Only the focused incident's ledger slice is loaded, so only it can report a planner error.
  const plannerErrors: Record<string, string> = {};
  if (detail.data) {
    const failure = plannerErrorOf(detail.data.timeline, detail.data.plan?.rationale);
    if (failure) plannerErrors[detail.data.incident.id] = failure;
  }

  return (
    <div className="ov">
      <Section
        title="Status"
        right={
          <span className="note mono">
            window {timeOnly(data.window.start)} to {timeOnly(data.window.end)} &middot; {data.clock}{" "}
            clock
          </span>
        }
      >
        <StatusStrip data={data} />
      </Section>

      <Section
        title="Active incidents"
        right={
          <span className="flex items-center gap-3">
            {run && (
              <span className="note mono">
                run {run.scenario} &middot; seed {run.seed} &middot; {run.variant}
              </span>
            )}
            <span className="fig-md">{String(incidents.length).padStart(2, "0")}</span>
          </span>
        }
      >
        <ActiveIncidents
          data={data}
          incidents={incidents}
          run={run}
          plannerErrors={plannerErrors}
        />
      </Section>

      <Section
        title="Payment health"
        right={<span className="note">success rate against each segment&rsquo;s own baseline</span>}
      >
        <PaymentHealth segments={data.segments} />
      </Section>

      <Section
        title="Traffic and incident windows"
        right={<span className="note">last 24 sim hours</span>}
      >
        <TrafficTimeline data={data} run={run} />
      </Section>

      {focusId && (
        <Section
          title="Incident lifecycle"
          right={
            detail.data && (
              <span className="flex items-center gap-2.5">
                <span className="note mono">{detail.data.incident.id}</span>
                <Chip flat>{causeLabel(detail.data.incident.root_cause)}</Chip>
              </span>
            )
          }
        >
          {detail.error ? (
            <ErrorPanel error={detail.error} retry={detail.reload} />
          ) : detail.data ? (
            <Lifecycle data={detail.data} />
          ) : (
            <Loading rows={2} label="Loading the lifecycle" />
          )}
        </Section>
      )}

      <Section title="Ledger activity">
        {ledger.error ? (
          <ErrorPanel error={ledger.error} retry={ledger.reload} />
        ) : ledger.data ? (
          <Activity page={ledger.data} clock={data.clock} />
        ) : (
          <Loading rows={4} label="Loading activity" />
        )}
      </Section>
    </div>
  );
}
