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

function Cell({ segment }: { segment: Segment }) {
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

function Heatmap({ segments }: { segments: Segment[] }) {
  const merchant = segments.find((segment) => segment.key === "all");
  const methods = ["upi", "card", "netbanking", "wallet"];
  const rest = segments.filter((segment) => segment.key !== "all");

  return (
    <div className="space-y-2">
      {merchant && (
        <div>
          {/* Pinned merchant-wide row. A fault that spans every method is attributed to the
              `all` key by the detector, so without this row it would have nowhere to appear. */}
          <Cell segment={merchant} />
        </div>
      )}
      {methods.map((method) => {
        const row = rest.filter((segment) => segment.method === method);
        if (row.length === 0) return null;
        return (
          <div key={method}>
            <div className="mb-1 text-xs font-medium uppercase tracking-wide text-neutral-600">
              {method}
            </div>
            <div className="grid grid-cols-2 gap-1 sm:grid-cols-4 lg:grid-cols-6">
              {row.map((segment) => (
                <Cell key={segment.key} segment={segment} />
              ))}
            </div>
          </div>
        );
      })}
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
        {(data) =>
          data.segments.length === 0 ? (
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
                  hint="open incidents"
                  tone={data.stats.at_risk_amount > 0 ? "amber" : "neutral"}
                />
                <Stat
                  label="Recovered"
                  value={rupees(data.stats.recovered_amount)}
                  hint="by link or steer"
                  tone="green"
                />
              </div>

              <Panel
                title="Success rate by segment"
                subtitle="Current 15-minute window. Baseline success rate and attempt count in small text. A red outline means the segment is inside an open incident."
              >
                <Heatmap segments={data.segments} />
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
                        <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
                          <div>
                            <div className="text-neutral-600">at risk</div>
                            <div className="num font-medium">{rupees(incident.at_risk_amount)}</div>
                          </div>
                          <div>
                            <div className="text-neutral-600">recovered</div>
                            <div className="num font-medium text-green-700">
                              {rupees(incident.recovered_amount)}
                            </div>
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
          )
        }
      </Region>
    </div>
  );
}
