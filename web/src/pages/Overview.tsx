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
import { PageIntro } from "../components/PageIntro";

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

export default function OverviewPage() {
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
      <div className="px-[var(--page-pad-x)] pt-[var(--space-6)]">
        <PageIntro
          title="Overview"
          what="The state of payments right now: what is succeeding, what is failing, and what the agent has done about it."
          use="Read top to bottom. It is ordered by severity, so the worst thing is highest. Click an incident to open it in full."
          shows={[
            ["Status", "success rate over the last 60 minutes, and separately how far the merchant-wide rate has moved from its own seven-day baseline. Two windows, so they are shown as two facts rather than subtracted into one"],
            ["Active incidents", "what the detector has opened, the cause it settled on, and how long it took to notice"],
            ["Payment health", "every segment against its own baseline, not against each other. The bar runs from that segment's normal rate to where it is now, so its length is the excess"],
            ["Traffic and incident windows", "the last 24 simulated hours of attempts, with the incident marked on it"],
            ["Incident lifecycle", "where the current incident has reached. Escalate is a terminal branch: nothing runs from it to recovery"],
            ["Ledger activity", "the most recent entries in the tamper-evident record"],
          ]}
          caveat="A segment with too little traffic to test is drawn as an empty dashed lane rather than left out. That is the detector declining to measure it, which is different from the segment being healthy."
        />
      </div>
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
