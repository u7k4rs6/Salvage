import { Link } from "react-router-dom";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useApi } from "../lib/useApi";
import { useStream } from "../lib/useStream";
import { Badge, Empty, Panel, Region, Stat, StatusBadge } from "../components/primitives";
import {
  causeLabel,
  count,
  isSyntheticIncident,
  percent,
  rupees,
  segmentLabel,
  timeOnly,
} from "../lib/format";
import {
  buildBoard,
  FLOOR_ATTEMPTS,
  type Board,
  type BoardGroup,
  type BoardNode,
} from "../board/roster";
import type { Overview as OverviewData, Segment } from "../lib/types";

/**
 * Neutral to red on the failure rate. Five steps, because a continuous gradient reads as noise on
 * a dense grid and an ops console is scanned, not admired.
 */
function cellColour(segment: Segment): string {
  const excess = segment.failure_rate - segment.baseline;
  if (segment.attempts === 0) return "bg-neutral-50 text-neutral-400";
  if (excess >= 0.3) return "bg-red-600 text-white";
  if (excess >= 0.15) return "bg-red-400 text-white";
  if (excess >= 0.07) return "bg-red-200 text-red-900";
  if (excess >= 0.03) return "bg-amber-100 text-amber-900";
  return "bg-neutral-100 text-neutral-700";
}

/**
 * A tile is measured or it is below the detection floor. The second state is not an error and not
 * a loading state: the detector needs 20 attempts in a 15-minute window before a key can be
 * tested at all, and most instruments are under that line for most of the day. The node stays on
 * the board because its absence from measurement is the thing worth seeing.
 */
function Cell({ node }: { node: BoardNode }) {
  if (node.state === "below_floor") {
    const peak = node.roster.expected_attempts_peak_window;
    // A node sitting near the floor is not reliably absent, it flips window to window on
    // ordinary noise. Saying so is better than implying the board has a fixed shape.
    const marginal = node.roster.marginal_at_peak
      ? " Sits close enough to the floor to appear in some windows and not others."
      : "";
    return (
      <div
        aria-label={`${node.instrument}, below the detection floor, no rate measured this window. About ${peak} attempts expected in a peak window against a floor of ${FLOOR_ATTEMPTS}.${marginal}`}
        title={`About ${peak} attempts expected in a peak 15-minute window. Floor is ${FLOOR_ATTEMPTS}.${marginal}`}
        className="h-full border border-dashed border-neutral-300 bg-neutral-50 px-2 py-1.5 text-neutral-400"
      >
        <div className="truncate text-[11px] font-medium">{node.instrument}</div>
        <div className="text-[10px] leading-tight">below detection floor</div>
      </div>
    );
  }

  const segment = node.segment;
  const inner = (
    <div
      // baseline arrives as a failure rate; every number on this cell is a success rate, so it
      // is converted here rather than leaving two conventions on one tile.
      aria-label={`${segmentLabel(segment.key)}, success rate ${percent(segment.rate)}, baseline success rate ${percent(1 - segment.baseline)}, ${segment.attempts} attempts${segment.incident_id ? ", inside an open incident" : ""}`}
      className={`h-full border ${
        segment.incident_id ? "border-2 border-red-600" : "border-neutral-200"
      } ${cellColour(segment)} px-2 py-1.5`}
    >
      <div className="truncate text-[11px] font-medium">{segment.instrument}</div>
      <div className="num text-sm font-semibold">{percent(segment.rate)}</div>
      <div className="num text-[10px] opacity-80">
        base {percent(1 - segment.baseline)} / n {segment.attempts}
      </div>
      {segment.incident_id && <div className="mt-0.5 text-[10px] font-semibold">incident</div>}
    </div>
  );
  return segment.incident_id ? (
    <Link to={`/incidents/${segment.incident_id}`} className="block h-full">
      {inner}
    </Link>
  ) : (
    inner
  );
}

/** A whole dimension folded into one row, because five empty tiles say less than one sentence. */
function CollapsedGroup({ group }: { group: BoardGroup }) {
  const collapsed = group.collapsed;
  if (!collapsed) return null;
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 border border-dashed border-neutral-300 bg-neutral-50 px-2 py-1.5">
      <span className="text-[11px] font-medium text-neutral-500">{group.title}</span>
      <span className="text-[11px] text-neutral-500">{collapsed.label}</span>
      <span className="text-[10px] text-neutral-400">{collapsed.detail}</span>
    </div>
  );
}

function Group({ group }: { group: BoardGroup }) {
  if (group.collapsed) return <CollapsedGroup group={group} />;
  if (group.nodes.length === 0) return null;
  return (
    <div>
      <div className="mb-1 flex flex-wrap items-baseline gap-x-2">
        <span className="text-[11px] font-medium text-neutral-600">{group.title}</span>
        {group.note && <span className="text-[10px] text-neutral-500">{group.note}</span>}
      </div>
      <div className="grid grid-cols-2 gap-1 sm:grid-cols-4 lg:grid-cols-6">
        {group.nodes.map((node) => (
          <Cell key={node.key} node={node} />
        ))}
      </div>
    </div>
  );
}

function Heatmap({ board }: { board: Board }) {
  return (
    <div className="space-y-3">
      {board.merchant && (
        <div>
          {/* Pinned merchant-wide row. A fault that spans every method is attributed to the
              `all` key by the detector, so without this row it would have nowhere to appear. */}
          <Cell node={board.merchant} />
        </div>
      )}
      {board.methods.map((entry) => (
        <div key={entry.method} className="border-t border-neutral-200 pt-2">
          <div className="mb-1 flex items-center gap-2">
            <span className="text-xs font-medium uppercase tracking-wide text-neutral-600">
              {entry.method}
            </span>
            {entry.methodNode && (
              <span className="num text-[11px] text-neutral-500">
                {entry.methodNode.state === "measured"
                  ? `${percent(entry.methodNode.segment.rate)} / n ${entry.methodNode.segment.attempts}`
                  : "below detection floor"}
              </span>
            )}
          </div>
          <div className="space-y-2">
            {entry.groups.map((group) => (
              <Group key={group.id} group={group} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export default function OverviewPage() {
  const state = useApi<OverviewData>("/api/overview");
  useStream(
    ["attempt", "incident.opened", "incident.updated", "incident.closed", "sim.finished"],
    () => state.reload(),
  );

  return (
    <div className="space-y-4">
      <Region
        state={state}
        empty={<span>No attempts yet. Run a scenario.</span>}
        rows={6}
      >
        {(data) => {
          const board = buildBoard(data.segments);
          return data.segments.length === 0 ? (
            <Panel title="Overview">
              <Empty
                action={
                  <Link to="/runner" className="text-sm text-accent hover:text-accent-hover">
                    Go to Scenario Runner
                  </Link>
                }
              >
                No attempts yet. Run a scenario.
              </Empty>
            </Panel>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <Stat
                  label="Attempts, last hour"
                  value={count(data.stats.attempts_last_hour)}
                  hint={`window ends ${timeOnly(data.window.end)} ${data.clock}`}
                />
                <Stat
                  label="Success rate, last hour"
                  value={percent(data.stats.success_rate)}
                  tone={
                    data.stats.success_rate !== null && data.stats.success_rate < 0.85
                      ? "red"
                      : "neutral"
                  }
                />
                <Stat
                  label="At-risk revenue"
                  value={rupees(data.stats.at_risk_amount)}
                  hint="open incidents, measured over each incident's detection window"
                  tone={data.stats.at_risk_amount > 0 ? "amber" : "neutral"}
                />
                {/* Deliberately not "recovered today". The route sums recovery_routes with no
                    time filter at all, and filters to the link and steer routes, so organic
                    recovery is not in it. The label says what the number is. */}
                <Stat
                  label="Recovered, all time"
                  value={rupees(data.stats.recovered_amount)}
                  hint="link and steer routes only, excludes organic recovery"
                  tone="green"
                />
              </div>

              <Panel
                title="Success rate by segment"
                subtitle={
                  <>
                    Current 15-minute window. Baseline success rate and attempt count in small
                    text. A red outline means the segment is inside an open incident.{" "}
                    <span className="num">
                      {board.measured} of {board.total}
                    </span>{" "}
                    segments cleared the {FLOOR_ATTEMPTS}-attempt floor in this window; the rest
                    are shown muted, because a segment the detector cannot test is a fact about
                    the detector, not missing data.
                  </>
                }
              >
                <Heatmap board={board} />
              </Panel>

              <Panel title="Active incidents">
                {data.incidents.length === 0 ? (
                  <Empty>Nothing open. Every segment is inside its baseline.</Empty>
                ) : (
                  <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                    {data.incidents.map((incident) => (
                      <Link
                        key={incident.id}
                        to={`/incidents/${incident.id}`}
                        className="block border border-red-300 bg-white p-3 hover:bg-red-50"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="num text-sm font-medium">
                            {segmentLabel(incident.segment_key)}
                          </span>
                          <StatusBadge status={incident.status} />
                        </div>
                        <div className="mt-1 text-xs text-neutral-700">
                          {isSyntheticIncident(incident.id)
                            ? "synthetic, opened by a baseline policy to hold its cases"
                            : causeLabel(incident.root_cause)}
                          {incident.confidence !== null && (
                            <span className="num text-neutral-500">
                              {" "}
                              confidence {incident.confidence.toFixed(2)}
                            </span>
                          )}
                        </div>
                        {/* Three separate figures, never a ratio. at risk is one detection
                            window, recovered is the incident's whole life and is not restricted
                            to the at-risk orders, so dividing them means nothing. The scope sits
                            under each number so nobody has to know that to read the card. */}
                        <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
                          <div>
                            <div className="text-neutral-600">at risk</div>
                            <div className="num font-medium">{rupees(incident.at_risk_amount)}</div>
                            <div className="text-[10px] text-neutral-500">detection window</div>
                          </div>
                          <div>
                            <div className="text-neutral-600">recovered</div>
                            <div className="num font-medium text-green-700">
                              {rupees(incident.recovered_amount)}
                            </div>
                            <div className="text-[10px] text-neutral-500">whole incident</div>
                          </div>
                          <div>
                            <div className="text-neutral-600">actions</div>
                            <div className="num font-medium">{count(incident.actions)}</div>
                            <div className="text-[10px] text-neutral-500">not messages</div>
                          </div>
                        </div>
                        {incident.escalated && (
                          <div className="mt-2">
                            <Badge tone="amber">escalated</Badge>
                          </div>
                        )}
                      </Link>
                    ))}
                  </div>
                )}
              </Panel>

              <Panel
                title="Volume and failures"
                subtitle="Last 24 sim hours, 15-minute buckets."
              >
                <div className="h-56">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={data.series}>
                      <CartesianGrid stroke="#e5e5e5" vertical={false} />
                      <XAxis
                        dataKey="t"
                        tickFormatter={timeOnly}
                        tick={{ fontSize: 11 }}
                        stroke="#737373"
                        minTickGap={40}
                      />
                      <YAxis tick={{ fontSize: 11 }} stroke="#737373" width={40} />
                      <Tooltip
                        labelFormatter={(value) => timeOnly(Number(value))}
                        contentStyle={{ fontSize: 12 }}
                      />
                      <Area
                        type="monotone"
                        dataKey="attempts"
                        stroke="#0f766e"
                        fill="#ccfbf1"
                        name="attempts"
                      />
                      <Area
                        type="monotone"
                        dataKey="failures"
                        stroke="#b91c1c"
                        fill="#fecaca"
                        name="failures"
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </Panel>
            </>
          );
        }}
      </Region>
    </div>
  );
}
