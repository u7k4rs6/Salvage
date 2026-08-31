import { useCallback, useMemo, useRef } from "react";
import type { Replay } from "../../replay/model";
import { timeOnly } from "../../lib/format";

/**
 * The scrub bar: the run's sim time, with what happened in it drawn on.
 *
 * Everything on this bar is a recorded fact, not an annotation somebody chose.
 *
 * Three of them are named in the legend, because three is what a viewer can hold: the fault the
 * simulator scheduled and wrote into `sim.run.started`, the incident from opened to closed, and
 * the beats.
 *
 * Where the entries are is drawn but not named. The density columns and the banding over a stretch
 * with no ledger entry in it are one neutral layer in the same grey, saying only "the run is busy
 * here and idle there". They were a hatched amber band and a separate shading with a legend entry
 * each, which needed a paragraph to explain and earned two of the five slots for something the eye
 * reads without being told.
 *
 * The ticks along the bottom are the beats: the first entry of a kind, and the first action
 * decided by a given rule. Refusals get a taller, red one. They are where the transport pauses
 * long enough to read, so the bar shows the operator where those are before they get there.
 */

const BUCKETS = 260;

export function Scrubber({
  replay,
  ts,
  onSeek,
  chrome = true,
}: {
  replay: Replay;
  ts: number;
  onSeek: (ts: number) => void;
  /** The legend. Off in presentation mode, where the shapes have already been explained aloud. */
  chrome?: boolean;
}) {
  const railRef = useRef<HTMLDivElement | null>(null);
  const span = Math.max(1, replay.end - replay.start);
  const pct = (value: number) => ((value - replay.start) / span) * 100;

  const density = useMemo(() => {
    const counts = new Array<number>(BUCKETS).fill(0);
    for (let index = replay.playFrom; index <= replay.playTo; index += 1) {
      const frame = replay.frames[index];
      const slot = Math.min(
        BUCKETS - 1,
        Math.max(0, Math.floor(((frame.ts - replay.start) / span) * BUCKETS)),
      );
      counts[slot] += 1;
    }
    const peak = Math.max(1, ...counts);
    return counts.map((count) => (count === 0 ? 0 : Math.max(2, (count / peak) * 30)));
  }, [replay, span]);

  const beats = useMemo(
    () =>
      replay.frames
        .slice(replay.playFrom, replay.playTo + 1)
        .filter((frame) => frame.held)
        .map((frame) => ({
          ord: frame.ord,
          ts: frame.ts,
          refusal: frame.kind === "execute.action.refused",
          label: frame.holdLabel,
        })),
    [replay],
  );

  const incidents = replay.recording.incidents.filter((row) => !row.id.endsWith("_baseline"));

  const ticks = useMemo(() => {
    // Six labels across the span, snapped to the hour so the row reads as a clock and not as
    // arbitrary offsets.
    const out: number[] = [];
    const step = Math.max(3600, Math.round(span / 6 / 3600) * 3600);
    const first = Math.ceil(replay.start / step) * step;
    for (let value = first; value <= replay.end; value += step) out.push(value);
    return out;
  }, [replay, span]);

  const seekFromClientX = useCallback(
    (clientX: number) => {
      const rail = railRef.current;
      if (!rail) return;
      const box = rail.getBoundingClientRect();
      const ratio = Math.min(1, Math.max(0, (clientX - box.left) / box.width));
      onSeek(replay.start + ratio * span);
    },
    [onSeek, replay.start, span],
  );

  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    seekFromClientX(event.clientX);
  };
  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.buttons !== 1) return;
    seekFromClientX(event.clientX);
  };
  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const nudge = event.shiftKey ? span / 20 : replay.stepSeconds * 15;
    if (event.key === "ArrowRight") {
      event.preventDefault();
      onSeek(ts + nudge);
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      onSeek(ts - nudge);
    } else if (event.key === "Home") {
      event.preventDefault();
      onSeek(replay.start);
    } else if (event.key === "End") {
      event.preventDefault();
      onSeek(replay.end);
    }
  };

  return (
    <div>
      <div
        ref={railRef}
        className="scrub"
        role="slider"
        tabIndex={0}
        aria-label="Sim time"
        aria-valuemin={replay.start}
        aria-valuemax={replay.end}
        aria-valuenow={Math.round(ts)}
        aria-valuetext={`${timeOnly(Math.round(ts))} sim time`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onKeyDown={onKeyDown}
      >
        {replay.faults.map((fault) => (
          <div
            key={`fault-${fault.start}`}
            className="span-fault"
            style={{
              left: `${pct(fault.start)}%`,
              width: `${Math.max(0.3, pct(fault.end) - pct(fault.start))}%`,
            }}
            title={`fault ${fault.label}, ${timeOnly(fault.start)} to ${timeOnly(fault.end)}`}
          />
        ))}

        {replay.gaps.map((gap) => (
          <div
            key={`gap-${gap.start}`}
            className="span-gap"
            style={{
              left: `${pct(gap.start)}%`,
              width: `${Math.max(0.3, pct(gap.end) - pct(gap.start))}%`,
            }}
            title={`no ledger entry for ${Math.round(gap.seconds / 60)} sim minutes`}
          />
        ))}

        {density.map((height, index) =>
          height === 0 ? null : (
            <div
              key={index}
              className="density"
              style={{ left: `${(index / BUCKETS) * 100}%`, height: `${height}px` }}
            />
          ),
        )}

        {incidents.map((row) => (
          <div
            key={row.id}
            className="span-incident"
            style={{
              left: `${pct(row.opened_at)}%`,
              width: `${Math.max(0.3, pct(row.closed_at ?? replay.end) - pct(row.opened_at))}%`,
            }}
            title={`incident ${row.id}`}
          />
        ))}

        {beats.map((beat) => (
          <div
            key={beat.ord}
            className={`beat${beat.refusal ? " beat-refusal" : ""}`}
            style={{ left: `${pct(beat.ts)}%` }}
            title={beat.label}
          />
        ))}

        <div className="head" style={{ left: `${pct(ts)}%` }} />
      </div>

      <div className="ticks mt-1">
        {ticks.map((value) => (
          <span key={value} className="tick lbl" style={{ left: `${pct(value)}%` }}>
            {timeOnly(value).slice(0, 5)}
          </span>
        ))}
      </div>

      {chrome && (
        <div className="note mt-1 flex flex-wrap items-center gap-x-4 gap-y-1">
          <Key colour="rgba(248,81,73,0.45)">fault window</Key>
          <Key colour="var(--danger)">incident open</Key>
          <Key colour="var(--info)">beat</Key>
        </div>
      )}
    </div>
  );
}

function Key({ colour, children }: { colour: string; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        aria-hidden="true"
        style={{ background: colour, width: 8, height: 8, borderRadius: 1, display: "inline-block" }}
      />
      {children}
    </span>
  );
}
