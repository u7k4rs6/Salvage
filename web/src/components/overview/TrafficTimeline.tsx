import { useMemo, useRef, useState } from "react";
import { Chip } from "./Chrome";
import { selectorLabel, type RunHeader } from "../../lib/useRunHeader";
import { count, percent, timeOnly } from "../../lib/format";
import type { Overview } from "../../lib/types";

/**
 * Traffic, failures and the incident windows over them.
 *
 * The question this has to answer is "when did the system degrade, how badly, and which incident
 * caused it", so it is three layers on one shared time axis rather than a chart of one series.
 *
 * Top pane is the success rate, which is the shape an operator reads first. Bottom pane is
 * attempt volume with the failed portion of each bucket filled in, so a drop in the rate can be
 * told apart from a drop in traffic: at 03:00 the rate wobbles because volume collapsed, not
 * because anything broke, and a rate line on its own hides that.
 *
 * Over both panes sit the windows. The injected fault comes from the run's ledger header and is
 * the ground truth for when the rail actually went bad; the detection marker is where the
 * detector opened its incident. The gap between them is the time to detect, and drawing them as
 * two different things rather than one band is the whole point of showing them together.
 *
 * Fills are flat and the failure series is amber rather than red, because the chart is history and
 * most of it is not an emergency. Red is kept for the marker on the incident that is open now.
 */

const W = 1000;
const RATE_H = 58;
const VOL_H = 74;

interface Bucket {
  t: number;
  attempts: number;
  failures: number;
  rate: number | null;
}

function useBuckets(data: Overview): Bucket[] {
  return useMemo(
    () =>
      data.series.map((point) => ({
        t: point.t,
        attempts: point.attempts,
        failures: point.failures,
        rate: point.attempts > 0 ? (point.attempts - point.failures) / point.attempts : null,
      })),
    [data.series],
  );
}

/** Position of a timestamp along the axis, 0 to 1, clamped to the drawn span. */
function xOf(ts: number, first: number, last: number): number {
  if (last <= first) return 0;
  return Math.min(1, Math.max(0, (ts - first) / (last - first)));
}

export function TrafficTimeline({ data, run }: { data: Overview; run: RunHeader | null }) {
  const buckets = useBuckets(data);
  const container = useRef<HTMLDivElement | null>(null);
  const [hover, setHover] = useState<number | null>(null);

  if (buckets.length === 0) return null;

  const first = buckets[0].t;
  const last = buckets[buckets.length - 1].t;
  const maxAttempts = Math.max(...buckets.map((b) => b.attempts), 1);
  const step = W / buckets.length;

  // The fault windows this run injected, clipped to the drawn span.
  const faults = (run?.faults ?? []).filter((fault) => fault.end_ts > first && fault.start_ts < last);
  const open = data.incidents.filter((incident) => !incident.id.endsWith("_baseline"));

  // The rate pane is clipped to the data instead of running 0 to 100. Over a full axis a drop
  // from 87 to 72 is eight pixels of a fifty-eight pixel pane and the degradation is invisible,
  // which defeats the purpose of drawing it. The axis is labelled at both ends and in the middle
  // so the floor is stated rather than implied.
  const rates = buckets.map((b) => b.rate).filter((r): r is number => r !== null);
  const rateFloor = Math.max(0, Math.floor(Math.min(...rates, 1) * 10) / 10 - 0.05);
  const rateSpan = Math.max(1 - rateFloor, 0.05);
  const rateY = (rate: number) => RATE_H - ((rate - rateFloor) / rateSpan) * RATE_H;

  const ratePath = (() => {
    const segments: string[] = [];
    let drawing = false;
    buckets.forEach((bucket, index) => {
      if (bucket.rate === null) {
        drawing = false;
        return;
      }
      const x = index * step + step / 2;
      segments.push(`${drawing ? "L" : "M"}${x.toFixed(1)},${rateY(bucket.rate).toFixed(1)}`);
      drawing = true;
    });
    return segments.join(" ");
  })();

  const onMove = (event: React.MouseEvent<HTMLDivElement>) => {
    const box = container.current?.getBoundingClientRect();
    if (!box) return;
    const ratio = (event.clientX - box.left) / box.width;
    const index = Math.round(ratio * (buckets.length - 1));
    setHover(Math.min(buckets.length - 1, Math.max(0, index)));
  };

  const active = hover === null ? null : buckets[hover];
  const hoverRatio = hover === null ? 0 : (hover * step + step / 2) / W;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-x-5 gap-y-2">
        <span className="note flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="inline-block h-[2px] w-3"
            style={{ background: "var(--fg-2)" }}
          />
          success rate
        </span>
        <span className="note flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="inline-block h-2 w-2"
            style={{ background: "var(--line-2)" }}
          />
          attempts
        </span>
        <span className="note flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="inline-block h-2 w-2"
            style={{ background: "var(--warn)" }}
          />
          failures
        </span>
        {faults.length > 0 && run && (
          <span className="note flex items-center gap-1.5">
            <span
              aria-hidden="true"
              className="inline-block h-2 w-2"
              style={{ background: "rgba(210, 153, 34, 0.16)", border: "1px solid var(--warn)" }}
            />
            {run.scenario} fault window
          </span>
        )}
        <span className="note ml-auto mono">
          {timeOnly(first)} to {timeOnly(last)} &middot; 15 min buckets
        </span>
      </div>

      <div className="flex items-stretch">
        {/* The axis gutter sits outside the plot, so a band positioned as a percentage of the
            plot is not shifted by the width of a label. */}
        <div className="relative w-10 shrink-0" aria-hidden="true">
          <span className="mono absolute right-2 text-[9.5px] dim" style={{ top: -4 }}>
            {percent(1, 0)}
          </span>
          <span
            className="mono absolute right-2 text-[9.5px] dim"
            style={{ top: RATE_H / 2 - 5 }}
          >
            {percent(rateFloor + rateSpan / 2, 0)}
          </span>
          <span className="mono absolute right-2 text-[9.5px] dim" style={{ top: RATE_H - 10 }}>
            {percent(rateFloor, 0)}
          </span>
          <span
            className="mono absolute right-2 text-[9.5px] dim"
            style={{ top: RATE_H + 10 }}
          >
            {count(maxAttempts)}
          </span>
          <span
            className="mono absolute right-2 text-[9.5px] dim"
            style={{ top: RATE_H + VOL_H + 2 }}
          >
            0
          </span>
        </div>

        <div
          ref={container}
          className="chart min-w-0 flex-1"
          onMouseMove={onMove}
          onMouseLeave={() => setHover(null)}
        >
        {/* Fault windows and the detection markers, drawn over both panes. */}
        <div className="pointer-events-none absolute inset-0 z-[1]">
          {faults.map((fault) => {
            const left = xOf(fault.start_ts, first, last) * 100;
            const right = xOf(fault.end_ts, first, last) * 100;
            return (
              <div
                key={`${fault.start_ts}-${fault.end_ts}`}
                className="absolute top-0 bottom-[18px]"
                style={{
                  left: `${left}%`,
                  width: `${Math.max(right - left, 0.3)}%`,
                  background: "rgba(210, 153, 34, 0.10)",
                  borderLeft: "1px solid var(--warn)",
                  borderRight: "1px dashed rgba(210, 153, 34, 0.5)",
                }}
              />
            );
          })}
          {open.map((incident) => (
            <div
              key={incident.id}
              className="absolute top-0 bottom-[18px]"
              style={{
                left: `${xOf(incident.opened_at, first, last) * 100}%`,
                width: 1,
                background: "var(--crit)",
              }}
            />
          ))}
          {hover !== null && (
            <div
              className="absolute top-0 bottom-[18px]"
              style={{ left: `${hoverRatio * 100}%`, width: 1, background: "var(--fg-3)" }}
            />
          )}
        </div>

        {/* Success rate. */}
        <svg
          className="block w-full"
          viewBox={`0 0 ${W} ${RATE_H}`}
          preserveAspectRatio="none"
          height={RATE_H}
          role="img"
          aria-label={`Success rate across ${buckets.length} fifteen-minute buckets`}
        >
          {[rateFloor + rateSpan / 2, 1].map((line) => (
            <line
              key={line}
              x1={0}
              x2={W}
              y1={rateY(line)}
              y2={rateY(line)}
              stroke="var(--line)"
              strokeWidth={1}
              vectorEffect="non-scaling-stroke"
            />
          ))}
          <path
            d={ratePath}
            fill="none"
            stroke="var(--fg-2)"
            strokeWidth={1.25}
            vectorEffect="non-scaling-stroke"
          />
        </svg>

        {/* Attempts, with the failed part of each bucket filled. */}
        <svg
          className="mt-3 block w-full"
          viewBox={`0 0 ${W} ${VOL_H}`}
          preserveAspectRatio="none"
          height={VOL_H}
          role="img"
          aria-label={`Attempt volume and failures, peaking at ${count(maxAttempts)} attempts in a bucket`}
        >
          {buckets.map((bucket, index) => {
            const h = (bucket.attempts / maxAttempts) * VOL_H;
            const fh = (bucket.failures / maxAttempts) * VOL_H;
            const x = index * step;
            const w = Math.max(step - 0.6, 0.4);
            return (
              <g key={bucket.t}>
                <rect x={x} y={VOL_H - h} width={w} height={h} fill="var(--line-2)" />
                <rect x={x} y={VOL_H - fh} width={w} height={fh} fill="var(--warn)" opacity={0.9} />
              </g>
            );
          })}
        </svg>

        {/* Axis. */}
        <div className="relative mt-1 h-[18px]">
          {buckets
            .map((bucket, index) => ({ bucket, index }))
            .filter(({ index }) => index % 16 === 0)
            .map(({ bucket, index }) => (
              <span
                key={bucket.t}
                className="mono absolute top-0 text-[10px]"
                style={{
                  left: `${((index * step + step / 2) / W) * 100}%`,
                  color: "var(--fg-3)",
                  transform: index === 0 ? undefined : "translateX(-50%)",
                }}
              >
                {timeOnly(bucket.t).slice(0, 5)}
              </span>
            ))}
        </div>

        {active && (
          <div
            className="chart-tip"
            style={{
              left: `calc(${hoverRatio * 100}% + ${hoverRatio > 0.6 ? "-176px" : "8px"})`,
              top: 0,
            }}
          >
            <div className="mono text-[11px]" style={{ color: "var(--fg)" }}>
              {timeOnly(active.t)}
            </div>
            <dl className="mt-1.5 space-y-0.5">
              <div className="flex justify-between gap-4">
                <dt className="note">success</dt>
                <dd className="mono text-[11px]">
                  {active.rate === null ? "-" : percent(active.rate)}
                </dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="note">attempts</dt>
                <dd className="mono text-[11px]">{count(active.attempts)}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="note">failures</dt>
                <dd className="mono warn text-[11px]">{count(active.failures)}</dd>
              </div>
            </dl>
          </div>
        )}
        </div>
      </div>

      {/* What the bands mean, as a line of facts rather than a paragraph. */}
      {run && faults.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
          {faults.map((fault) => (
            <span
              key={`${fault.start_ts}-legend`}
              className="note flex flex-wrap items-center gap-x-2"
            >
              <Chip flat>{run.scenario}</Chip>
              <span className="mono">{selectorLabel(fault)}</span>
              <span className="mono dim">
                {timeOnly(fault.start_ts)} to {timeOnly(fault.end_ts)}
              </span>
              {fault.end_ts > data.now && <Chip severity="warn">active</Chip>}
            </span>
          ))}
          {open.map((incident) => (
            <span key={`${incident.id}-legend`} className="note flex items-center gap-2">
              <span
                aria-hidden="true"
                className="inline-block h-3 w-[2px]"
                style={{ background: "var(--crit)" }}
              />
              detected {timeOnly(incident.opened_at)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
