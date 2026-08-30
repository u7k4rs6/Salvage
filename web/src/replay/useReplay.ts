import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { GAP_MIN_SECONDS, ordAt, type Frame, type Replay } from "./model";

/**
 * The transport.
 *
 * Position is a frame ordinal with a sim clock hung off it, and both are held in one state object
 * so no render can ever see one of them updated and the other not. Nothing else on the page holds
 * timing state.
 *
 * Two clocks run here, and they are different in kind, which is the whole reason this is not a
 * plain timer.
 *
 * Sim time. Between entries the clock advances at the speed multiplier, and the multiplier means
 * what it says: 1x is one sim minute per real second, which is one detector window step. The
 * detector evaluates every sim minute, so at 1x a window passes a second, and the traffic panel
 * moves once per second.
 *
 * Reading pace. Several entries share one sim second: the detection, the diagnosis, the plan and
 * the first forty six deferrals all carry the same timestamp, and so do the fifty eight refusals
 * and the hundred and one quiet-hours queues at the moment the segment recovers. Nothing recorded
 * a duration for them, because none elapsed. The speed multiplier therefore cannot pace them, and
 * pretending it could would mean inventing time that the run did not spend. They are stepped at a
 * fixed reading pace instead, and the transport says so on screen.
 */

export type Speed = "1x" | "10x" | "60x" | "step";

/** Sim seconds per real second. 1x is one sim minute, which is one detector window step. */
const SIM_RATE: Record<Exclude<Speed, "step">, number> = {
  "1x": 60,
  "10x": 600,
  "60x": 3600,
};

/** Entries per real second inside a cluster of entries sharing one sim second. */
const CLUSTER_RATE: Record<Exclude<Speed, "step">, number> = {
  "1x": 4,
  "10x": 14,
  "60x": 40,
};

/**
 * How long a beat is held, in real seconds, whatever the speed.
 *
 * A refusal gets the longest hold on the page. It is the frame the run is hardest to believe
 * without seeing, and it has to be readable at 10x, so it does not scale with the multiplier.
 */
const HOLD_SECONDS = 0.85;
const REFUSAL_HOLD_SECONDS = 1.6;

/**
 * How long the head takes to cross a recorded stretch with no entries in it.
 *
 * The gap is not skipped. The clock really does run through it and the readout counts it off,
 * because the ten and a half hours the agent spends holding sends for quiet hours is a thing the
 * system did, not dead air to be edited out. What is capped is how long a viewer waits to see it
 * happen.
 */
const GAP_TRAVERSAL_SECONDS = 3.5;

/** A tab that was in the background must not consume the run in one animation frame. */
const MAX_TICK_SECONDS = 0.25;

export interface Cursor {
  ord: number;
  ts: number;
}

export interface Transport {
  ord: number;
  ts: number;
  playing: boolean;
  speed: Speed;
  atEnd: boolean;
  /** The gap the head is inside, if any. Drives the waiting banner. */
  inGap: { start: number; end: number; seconds: number } | null;
  /** True while a beat is being held, so the transport can say why it paused on this frame. */
  holding: boolean;
  setSpeed: (speed: Speed) => void;
  play: () => void;
  pause: () => void;
  toggle: () => void;
  step: (delta?: number) => void;
  /** Jump to the next or previous held beat. */
  stepBeat: (delta: number) => void;
  seekTo: (ts: number) => void;
  restart: () => void;
}

function holdSecondsFor(frame: Frame): number {
  if (!frame.held) return 0;
  return frame.kind === "execute.action.refused" ? REFUSAL_HOLD_SECONDS : HOLD_SECONDS;
}

export function useReplay(replay: Replay): Transport {
  const initial = useMemo<Cursor>(
    () => ({ ord: replay.playFrom, ts: replay.start }),
    [replay],
  );
  const [cursor, setCursor] = useState<Cursor>(initial);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeedState] = useState<Speed>("10x");
  const [holding, setHolding] = useState(false);

  // Real seconds already spent on the frame the head is waiting to consume. Kept in a ref because
  // it is a property of the animation loop and not of what is on screen.
  const dwellRef = useRef(0);
  const lastRef = useRef<number | null>(null);

  useEffect(() => {
    setCursor(initial);
    setPlaying(false);
    setHolding(false);
    dwellRef.current = 0;
  }, [initial]);

  const atEnd = cursor.ord >= replay.playTo && cursor.ts >= replay.end;

  const setSpeed = useCallback((next: Speed) => {
    setSpeedState(next);
    // Stepping is a mode, not a rate. Choosing it stops the clock so the next thing that moves is
    // the operator's own step.
    if (next === "step") setPlaying(false);
  }, []);

  const pause = useCallback(() => setPlaying(false), []);
  const play = useCallback(() => {
    setSpeedState((current) => (current === "step" ? "10x" : current));
    setPlaying(true);
  }, []);
  const toggle = useCallback(() => setPlaying((current) => !current), []);

  const step = useCallback(
    (delta = 1) => {
      setPlaying(false);
      dwellRef.current = 0;
      setCursor((current) => {
        const next = Math.min(replay.playTo, Math.max(replay.playFrom, current.ord + delta));
        return { ord: next, ts: replay.frames[next].ts };
      });
    },
    [replay],
  );

  const stepBeat = useCallback(
    (delta: number) => {
      setPlaying(false);
      dwellRef.current = 0;
      setCursor((current) => {
        let index = current.ord;
        while (true) {
          index += delta;
          if (index < replay.playFrom || index > replay.playTo) {
            const clamped = Math.min(replay.playTo, Math.max(replay.playFrom, index));
            return { ord: clamped, ts: replay.frames[clamped].ts };
          }
          if (replay.frames[index].held) return { ord: index, ts: replay.frames[index].ts };
        }
      });
    },
    [replay],
  );

  const seekTo = useCallback(
    (ts: number) => {
      dwellRef.current = 0;
      const clamped = Math.min(replay.end, Math.max(replay.start, ts));
      const ord = Math.min(replay.playTo, Math.max(replay.playFrom, ordAt(replay, clamped)));
      setCursor({ ord, ts: clamped });
    },
    [replay],
  );

  const restart = useCallback(() => {
    dwellRef.current = 0;
    setHolding(false);
    setCursor(initial);
  }, [initial]);

  // The cursor the loop reads. State drives the render; this mirrors it so the animation frame can
  // compute the next position without reading through a setter. The advance below has to be a
  // plain computation rather than a state updater: StrictMode invokes an updater twice, and an
  // updater that consumed a time budget would consume it twice and halve the speed, which is
  // exactly what it did.
  const cursorRef = useRef(cursor);
  useEffect(() => {
    cursorRef.current = cursor;
  }, [cursor]);

  useEffect(() => {
    if (!playing || speed === "step") {
      lastRef.current = null;
      return;
    }
    let handle = 0;
    const rate = SIM_RATE[speed];
    const clusterDwell = 1 / CLUSTER_RATE[speed];

    const tick = (now: number) => {
      const previous = lastRef.current;
      lastRef.current = now;
      if (previous === null) {
        handle = requestAnimationFrame(tick);
        return;
      }

      let budget = Math.min(MAX_TICK_SECONDS, (now - previous) / 1000);
      let { ord, ts } = cursorRef.current;
      let held = false;
      let finished = false;
      let guard = 0;

      while (budget > 0 && guard < 5000) {
        guard += 1;
        if (ord >= replay.playTo) {
          ts = replay.end;
          finished = true;
          break;
        }
        const next = replay.frames[ord + 1];
        if (next.ts > ts) {
          // Sim time to cross before the next entry. A stretch the recording has no entry in at
          // all is crossed at a pace that gets the head over it in a few seconds whatever the
          // multiplier, so a ten hour wait is visible without being sat through. The clock still
          // runs through every second of it and the readout still counts them.
          const whole = next.ts - Math.max(replay.frames[ord].ts, replay.start);
          const crossing = whole >= GAP_MIN_SECONDS ? whole / GAP_TRAVERSAL_SECONDS : rate;
          const need = (next.ts - ts) / crossing;
          if (need > budget) {
            ts += budget * crossing;
            budget = 0;
          } else {
            ts = next.ts;
            budget -= need;
          }
          continue;
        }
        // The next entry shares this sim second. Nothing recorded a duration for it, so it is
        // consumed at the reading pace instead of at the clock's.
        const dwell = next.held ? holdSecondsFor(next) : clusterDwell;
        const spent = dwellRef.current;
        if (spent + budget < dwell) {
          dwellRef.current = spent + budget;
          budget = 0;
          held = next.held;
          break;
        }
        budget -= dwell - spent;
        dwellRef.current = 0;
        ord += 1;
        ts = next.ts;
      }

      const moved = ord !== cursorRef.current.ord || ts !== cursorRef.current.ts;
      if (moved) {
        cursorRef.current = { ord, ts };
        setCursor({ ord, ts });
      }
      setHolding((current) => (current === held ? current : held));
      if (finished) {
        setPlaying(false);
        return;
      }
      handle = requestAnimationFrame(tick);
    };

    handle = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(handle);
      lastRef.current = null;
    };
  }, [playing, speed, replay]);

  const inGap = useMemo(() => {
    const gap = replay.gaps.find((entry) => cursor.ts > entry.start && cursor.ts < entry.end);
    return gap ? { start: gap.start, end: gap.end, seconds: gap.seconds } : null;
  }, [replay, cursor.ts]);

  return {
    ord: cursor.ord,
    ts: cursor.ts,
    playing,
    speed,
    atEnd,
    inGap,
    holding: holding && playing,
    setSpeed,
    play,
    pause,
    toggle,
    step,
    stepBeat,
    seekTo,
    restart,
  };
}
