import { count, timeOnly } from "../../lib/format";
import type { Overview } from "../../lib/types";

/**
 * Attempts and failures over the last 24 sim hours, in 15-minute buckets.
 *
 * Drawn by hand rather than with the chart library the other pages use, because everything this
 * needs is two paths and two labels, and the library's defaults are built for the light frame.
 * There are no gridlines and no axis furniture: the shape is the point, and the exact values are
 * a hover away in the figures above it.
 *
 * The series is whatever `GET /api/overview` returned, bounded at the current window. Nothing is
 * smoothed, resampled or extended.
 */

const HEIGHT = 132;
const WIDTH = 1000; // A viewBox unit, stretched to the container by preserveAspectRatio.

function path(points: number[], max: number, close: boolean): string {
  if (points.length === 0) return "";
  const step = WIDTH / Math.max(points.length - 1, 1);
  const y = (value: number) => HEIGHT - (max === 0 ? 0 : (value / max) * HEIGHT);
  const line = points.map((value, index) => `${index === 0 ? "M" : "L"}${index * step},${y(value)}`);
  if (!close) return line.join(" ");
  return `${line.join(" ")} L${WIDTH},${HEIGHT} L0,${HEIGHT} Z`;
}

export function Volume({ data }: { data: Overview }) {
  const series = data.series;
  if (series.length === 0) return null;

  const attempts = series.map((point) => point.attempts);
  const failures = series.map((point) => point.failures);
  const max = Math.max(...attempts, 1);
  const peak = Math.max(...failures);

  return (
    <figure className="m-0">
      <div className="flex flex-wrap items-baseline justify-between gap-4">
        <div className="microlabel">Volume and failures</div>
        <div className="scope">
          Last 24 sim hours, 15-minute buckets, bounded at the current window. Peak{" "}
          {count(peak)} failures in a bucket.
        </div>
      </div>

      <svg
        className="mt-4 block w-full"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        preserveAspectRatio="none"
        height={HEIGHT}
        role="img"
        aria-label={`Attempts and failures across ${series.length} fifteen-minute buckets, peaking at ${count(max)} attempts and ${count(peak)} failures.`}
      >
        <path d={path(attempts, max, true)} fill="rgba(255,255,255,0.05)" />
        <path
          d={path(attempts, max, false)}
          fill="none"
          stroke="rgba(255,255,255,0.28)"
          strokeWidth={1}
          vectorEffect="non-scaling-stroke"
        />
        <path
          d={path(failures, max, false)}
          fill="none"
          stroke="var(--incident)"
          strokeWidth={1.5}
          vectorEffect="non-scaling-stroke"
        />
      </svg>

      <figcaption
        className="mono mt-2 flex justify-between"
        style={{ fontSize: 10, color: "var(--text-3)", borderTop: "1px solid var(--hair)", paddingTop: 8 }}
      >
        <span>{timeOnly(series[0].t)}</span>
        <span>{timeOnly(series[series.length - 1].t)}</span>
      </figcaption>
    </figure>
  );
}
