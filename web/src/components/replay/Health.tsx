import { useMemo } from "react";
import { windowAt, type Replay } from "../../replay/model";
import type { IncidentRecord } from "../../replay/state";
import {
  SEVERITY_CLASS,
  SEVERITY_COLOUR,
  baselineSuccess,
  deviationArrow,
  deviationPoints,
  deviationSeverity,
  formatPoints,
} from "../../lib/health";
import { count, percent, segmentLabel, timeOnly } from "../../lib/format";
import type { Segment } from "../../lib/types";

/**
 * Payment health at the cursor, window by window.
 *
 * Same encoding as the Overview, because it is the same fact: the bar runs from the segment's own
 * baseline to where it is now on a shared 0 to 100 axis, so its length is the excess and its
 * direction is the sign.
 *
 * The rows come from `segments_stats`, which the detector wrote one row per key per window it
 * could test. A key with fewer than twenty attempts in a window has no row, and this draws a
 * dashed empty track there rather than carrying the last value forward. That absence is a fact
 * about the detector, not a hole to be filled: it declined to measure the key, and interpolating
 * would be inventing traffic.
 *
 * The window shown is the one whose right edge is at the cursor. The detector's window is fifteen
 * sim minutes evaluated every minute, so the panel steps once per sim minute of playback.
 */

function asSegment(
  key: string,
  window: { attempts: number; failures: number; baselineRate: number },
  incidentId: string | null,
): Segment {
  const rate = window.attempts > 0 ? (window.attempts - window.failures) / window.attempts : 0;
  return {
    key,
    method: key.split(":")[0],
    instrument: segmentLabel(key),
    attempts: window.attempts,
    failures: window.failures,
    rate,
    failure_rate: window.attempts > 0 ? window.failures / window.attempts : 0,
    baseline: window.baselineRate,
    incident_id: incidentId,
  };
}

export function Health({
  replay,
  ts,
  incident,
}: {
  replay: Replay;
  ts: number;
  incident: IncidentRecord | null;
}) {
  const scope = useMemo(
    () => new Set(incident ? [incident.segmentKey, ...incident.scope] : []),
    [incident],
  );

  const rows = replay.healthKeys.map((key) => {
    const window = windowAt(replay, key, ts);
    return { key, window, inScope: scope.has(key) };
  });

  const windowEnd = Math.floor(ts / replay.stepSeconds) * replay.stepSeconds;

  return (
    <div>
      <div className="lane">
        <div className="lbl">Segment</div>
        <div className="lbl">Baseline to now</div>
        <div className="lbl text-right">Success</div>
        <div className="lbl text-right">Deviation</div>
        <div className="lbl text-right">Attempts</div>
      </div>
      <div className="divide">
        {rows.map(({ key, window, inScope }) => {
          if (!window) {
            return (
              <div key={key} className="lane row-hover">
                <div className="mono note truncate" title={key}>
                  {segmentLabel(key)}
                </div>
                <div
                  className="track"
                  role="img"
                  aria-label={`${segmentLabel(key)}: not measurable in this window`}
                >
                  <div className="track-empty" />
                </div>
                <div className="note text-right">not measured</div>
                <div className="note text-right">-</div>
                <div className="mono note text-right">
                  n &lt; {replay.recording.meta.detector.min_attempts}
                </div>
              </div>
            );
          }
          const segment = asSegment(key, window, inScope && incident ? incident.id : null);
          const points = deviationPoints(segment);
          const severity = deviationSeverity(points);
          const baseline = baselineSuccess(segment);
          const left = Math.min(segment.rate, baseline);
          const width = Math.max(Math.abs(segment.rate - baseline), 0.002);
          return (
            <div key={key} className="lane row-hover">
              <div className="flex items-center gap-2 truncate">
                {inScope && (
                  <span
                    aria-hidden="true"
                    className="dot"
                    style={{ background: "var(--danger)", flex: "none" }}
                  />
                )}
                <span className="mono truncate text-[length:var(--fs-meta)]" title={key}>
                  {segmentLabel(key)}
                </span>
              </div>
              <div
                className="track"
                role="img"
                aria-label={`${segment.instrument}: ${percent(segment.rate)} success against a ${percent(baseline)} baseline over ${segment.attempts} attempts`}
              >
                <div
                  className="bar"
                  style={{
                    left: `${left * 100}%`,
                    width: `${width * 100}%`,
                    background: SEVERITY_COLOUR[severity],
                    opacity: severity === "idle" ? 0.55 : segment.rate < baseline ? 0.85 : 0.6,
                  }}
                />
                <div className="baseline" style={{ left: `${baseline * 100}%` }} />
              </div>
              <div className="fig-md text-right">{percent(segment.rate)}</div>
              <div className="text-right">
                <span className={`mono text-[length:var(--fs-micro)] ${SEVERITY_CLASS[severity]}`}>
                  {deviationArrow(points)} {formatPoints(points)}
                </span>
              </div>
              <div className="mono note text-right">n {count(segment.attempts)}</div>
            </div>
          );
        })}
      </div>
      <p className="note mt-3">
        The detector&rsquo;s window is {replay.windowSeconds / 60} sim minutes, evaluated every{" "}
        {replay.stepSeconds} seconds. This is the window ending {timeOnly(windowEnd)}. A segment with
        fewer than {replay.recording.meta.detector.min_attempts} attempts in it has no recorded row
        and is drawn empty, because the detector did not measure it.
      </p>
    </div>
  );
}
