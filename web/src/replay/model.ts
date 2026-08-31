import type {
  ActionPayload,
  GateRecord,
  Recording,
  SimRunStartedPayload,
} from "./types";

/**
 * A recording turned into an ordered, immutable frame list.
 *
 * Everything the page shows is a function of one integer, the frame ordinal, and one number, the
 * sim clock. This module builds the structures those two look things up in and computes nothing
 * that is not in the recording.
 *
 * Ordering is `(ts, seq)`, never `seq` alone. The detector writes every incident entry to the
 * ledger before the agent writes anything, so `detect.incident.closed` sits at sequence 4 with a
 * timestamp ten hours after `execute.action.executed` at sequence 7. Sequence still does useful
 * work: it is the causal order inside a single sim second, of which this recording has several.
 */

export type FrameSource = "ledger" | "cases";

export interface Frame {
  /** Position in the replay. The canonical cursor. */
  ord: number;
  /** Sort key: the ledger sequence, or a value past every sequence for a table-dump frame. */
  sortKey: number;
  ts: number;
  /** Ledger sequence, or null for a frame read out of a table dump. */
  seq: number | null;
  source: FrameSource;
  kind: string;
  refType: string;
  refId: string;
  payload: unknown;
  hash: string | null;
  /**
   * A beat worth stopping on: the first time an outcome of this shape occurs. Held frames get a
   * reading pause that does not shrink with the speed multiplier, because a cluster of entries
   * sharing one sim second has no recorded duration for the speed to scale.
   */
  held: boolean;
  /** Why it is held, shown on the transport. Empty when it is not. */
  holdLabel: string;
}

/** A stretch of sim time the recording has no entry in. */
export interface Gap {
  start: number;
  end: number;
  seconds: number;
}

export interface SegmentWindow {
  windowStart: number;
  attempts: number;
  failures: number;
  /** A failure rate, as the detector records it. */
  baselineRate: number;
  pValue: number;
}

export interface FaultWindow {
  start: number;
  end: number;
  selector: Record<string, string>;
  label: string;
}

export interface Replay {
  recording: Recording;
  frames: Frame[];
  /**
   * The ordinals the transport plays between.
   *
   * Every entry is in `frames`, including the two bookends: `sim.run.started` is stamped a week
   * before the evaluation day and `sim.run.finished` at the end of the settlement tail, days after
   * the last thing that happens. They are real entries and the chain verifies over all of them,
   * but a scrub bar that spanned them would be nine tenths empty, so the transport runs across the
   * window the run was actually observed in and the bookends sit either side of it.
   */
  playFrom: number;
  playTo: number;
  /** Sim seconds the scrub bar spans. */
  start: number;
  end: number;
  gaps: Gap[];
  /** Recorded faults, from the sim.run.started payload. Ground truth the simulator wrote down. */
  faults: FaultWindow[];
  /** Segment key to its windows, ascending. */
  windows: Map<string, SegmentWindow[]>;
  /** Keys the health panel draws, in the Overview's order. */
  healthKeys: string[];
  /** Sim seconds a detector window covers. */
  windowSeconds: number;
  stepSeconds: number;
}

/** Sort keys for table-dump frames start past any ledger sequence, so at an equal timestamp a
 *  transition read out of a table lands after the chain entries of that same second. */
const CASE_SORT_BASE = 1e12;

/**
 * A stretch this long with no ledger entry in it is banded on the scrub bar and narrated rather
 * than passed over in silence.
 *
 * An hour, because the run has two stretches worth naming and a shorter threshold buries them:
 * the twenty hours of ordinary trading before the fault, and the ten and a half hours the agent
 * spends holding sends for quiet hours. At twenty minutes the settlement tail bands into a dozen
 * strips that mean nothing.
 */
export const GAP_MIN_SECONDS = 60 * 60;

/** The first gate a ladder failed on, which is the rule that decided the outcome. */
export function decidingRule(gates: GateRecord[]): GateRecord | null {
  return gates.find((gate) => !gate.passed) ?? null;
}

export function actionStatusOf(kind: string): string {
  return kind.startsWith("execute.action.") ? kind.slice("execute.action.".length) : "";
}

/**
 * Terminal case states the ledger does not record.
 *
 * RECOVERED has `execute.link_paid` and OPTED_OUT has `channel.opt_out`, so those cases resolve
 * from the chain. ABANDONED and PAID_ELSEWHERE write nothing at all, and without the case table
 * they would sit in WAITING for the rest of the run. `recovery_cases.updated_at` is the moment of
 * the last transition, so the resolution time is recorded even though the transition is not.
 */
const UNCHAINED_TERMINALS = new Set(["ABANDONED", "PAID_ELSEWHERE"]);

function faultLabel(selector: Record<string, string>): string {
  const parts = Object.entries(selector)
    .filter(([key]) => key !== "method")
    .map(([, value]) => value);
  const method = selector.method ? selector.method.toUpperCase() : "";
  return [method, ...parts].filter(Boolean).join(" ");
}

/**
 * Which frames are beats.
 *
 * The rule is novelty, read off the data rather than chosen by hand: the first entry of a kind,
 * and for an action the first one with a given (status, deciding rule) pair. That lands a hold on
 * each of the four gate outcomes this recording contains and on nothing else, so a run with a
 * fifth outcome would get a fifth hold without anybody editing a list.
 */
function markHeld(frames: Frame[]): void {
  const seenKinds = new Set<string>();
  const seenOutcomes = new Set<string>();
  for (const frame of frames) {
    if (frame.kind.startsWith("execute.action.")) {
      const status = actionStatusOf(frame.kind);
      const payload = frame.payload as ActionPayload;
      const decided = decidingRule(payload.gates ?? []);
      const signature = `${status}:${decided ? decided.rule : "all-passed"}`;
      if (!seenOutcomes.has(signature)) {
        seenOutcomes.add(signature);
        frame.held = true;
        frame.holdLabel = decided
          ? `first ${status} on ${decided.rule}`
          : `first ${status} ${payload.type}`;
      }
      seenKinds.add(frame.kind);
      continue;
    }
    if (!seenKinds.has(frame.kind)) {
      seenKinds.add(frame.kind);
      // sim.run.started and sim.run.finished are bookends outside the acted window and there is
      // nothing to read on them, so they are not beats.
      if (frame.kind !== "sim.run.started" && frame.kind !== "sim.run.finished") {
        frame.held = true;
        frame.holdLabel = `first ${frame.kind}`;
      }
    }
  }
}

export function buildReplay(recording: Recording): Replay {
  const frames: Frame[] = [];

  for (const entry of recording.ledger) {
    frames.push({
      ord: 0,
      sortKey: entry.seq,
      ts: entry.ts,
      seq: entry.seq,
      source: "ledger",
      kind: entry.kind,
      refType: entry.ref_type,
      refId: entry.ref_id,
      payload: JSON.parse(entry.payload_json),
      hash: entry.hash,
      held: false,
      holdLabel: "",
    });
  }

  recording.recovery_cases.forEach((row, index) => {
    if (!row.outcome || !UNCHAINED_TERMINALS.has(row.outcome)) return;
    frames.push({
      ord: 0,
      sortKey: CASE_SORT_BASE + index,
      ts: row.updated_at,
      seq: null,
      source: "cases",
      kind: `case.${row.outcome.toLowerCase()}`,
      refType: "case",
      refId: row.id,
      payload: { case_id: row.id, state: row.state, outcome: row.outcome },
      hash: null,
      held: false,
      holdLabel: "",
    });
  });

  frames.sort((a, b) => a.ts - b.ts || a.sortKey - b.sortKey);
  frames.forEach((frame, index) => {
    frame.ord = index;
  });
  markHeld(frames);

  // -- span ---------------------------------------------------------------
  //
  // sim.run.finished is stamped at the end of the settlement tail, days after the last thing that
  // happens, and sim.run.started a week before the evaluation day. Both are real entries and both
  // are in the frame list, but the scrub bar spans the window the run was actually observed in,
  // which is what the recording's own `span` records.
  //
  // The left edge is pulled forward by one detector window. A window stamped `window_start` covers
  // the fifteen minutes after it, so its result is not known until `window_start + window_seconds`
  // and a cursor before that has no measured segment anywhere. Opening on that instant showed a
  // panel of "not measured" for every row, which reads as a broken payload rather than as the one
  // window of warm-up it is.
  const windowSeconds = recording.meta.detector.window_seconds;
  const firstWindow = recording.segments_stats.rows.reduce(
    (lowest, row) => Math.min(lowest, row[1]),
    Number.POSITIVE_INFINITY,
  );
  const start = Number.isFinite(firstWindow)
    ? Math.max(recording.meta.span.start, firstWindow + windowSeconds)
    : recording.meta.span.start;
  const end = recording.meta.span.end;

  // -- gaps ---------------------------------------------------------------
  //
  // Measured from the left edge of the span, not from the first entry inside it. The longest
  // stretch on this run is the one before anything has happened at all, and leaving it unmarked
  // made the bar claim the run starts busy.
  const gaps: Gap[] = [];
  const inSpan = frames.filter((frame) => frame.ts >= start && frame.ts <= end);
  const marks = [start, ...inSpan.map((frame) => frame.ts), end];
  for (let index = 0; index < marks.length - 1; index += 1) {
    const seconds = marks[index + 1] - marks[index];
    if (seconds >= GAP_MIN_SECONDS) {
      gaps.push({
        start: marks[index],
        end: marks[index + 1],
        seconds,
      });
    }
  }

  // -- faults -------------------------------------------------------------
  const startedEntry = recording.ledger.find((entry) => entry.kind === "sim.run.started");
  const started = startedEntry
    ? (JSON.parse(startedEntry.payload_json) as SimRunStartedPayload)
    : null;
  const faults: FaultWindow[] = (started?.faults ?? []).map((fault) => ({
    start: fault.start_ts,
    end: fault.end_ts,
    selector: fault.selector,
    label: faultLabel(fault.selector),
  }));

  // -- windows ------------------------------------------------------------
  const windows = new Map<string, SegmentWindow[]>();
  const { keys, rows } = recording.segments_stats;
  for (const row of rows) {
    const key = keys[row[0]];
    let list = windows.get(key);
    if (!list) {
      list = [];
      windows.set(key, list);
    }
    list.push({
      windowStart: row[1],
      attempts: row[2],
      failures: row[3],
      baselineRate: row[4],
      pValue: row[5],
    });
  }
  for (const list of windows.values()) list.sort((a, b) => a.windowStart - b.windowStart);

  let playFrom = frames.findIndex((frame) => frame.ts >= start);
  if (playFrom < 0) playFrom = 0;
  // The started entry is the run's own declaration of its faults, so the replay opens on it
  // rather than on the first frame inside the span.
  playFrom = Math.max(0, playFrom - 1);
  let playTo = playFrom;
  for (let index = frames.length - 1; index >= 0; index -= 1) {
    if (frames[index].ts <= end) {
      playTo = index;
      break;
    }
  }

  return {
    recording,
    frames,
    playFrom,
    playTo,
    start,
    end,
    gaps,
    faults,
    windows,
    healthKeys: healthKeysFor(recording, windows),
    windowSeconds: recording.meta.detector.window_seconds,
    stepSeconds: recording.meta.detector.step_seconds,
  };
}

const HEATMAP_METHODS = ["upi", "card", "netbanking", "wallet"];

/**
 * The health panel's rows, in the Overview's order: the merchant-wide key pinned first, then the
 * four methods, then every instrument key.
 *
 * `error_step` keys are left out, exactly as the Overview leaves them out: they are a dimension of
 * where in a flow a payment died, not a segment of traffic, and a row per step triples the panel
 * without adding a thing anyone reads. An incident's scope can still contain one, and the incident
 * panel prints the scope in full.
 */
function healthKeysFor(recording: Recording, windows: Map<string, SegmentWindow[]>): string[] {
  const present = new Set(windows.keys());
  const ordered: string[] = [];
  const push = (key: string) => {
    if (present.has(key) && !ordered.includes(key)) ordered.push(key);
  };
  push("all");
  for (const method of HEATMAP_METHODS) push(method);
  const rest = [...present]
    .filter((key) => key !== "all" && !HEATMAP_METHODS.includes(key))
    .filter((key) => !key.includes(":error_step:"))
    .sort();
  for (const key of rest) push(key);
  // An incident's own segment is always drawn, even if the rule above would have dropped it.
  for (const incident of recording.incidents) push(incident.segment_key);
  return ordered;
}

/**
 * The window in force at sim time `ts`: the one whose right edge is at or just behind the cursor.
 *
 * A row exists only for a window where the key had at least `min_attempts`, so a key that went
 * quiet has no row and this returns null. The caller draws nothing there. Interpolating from the
 * last window it was live in would be inventing traffic that the detector explicitly declined to
 * measure.
 */
export function windowAt(
  replay: Replay,
  key: string,
  ts: number,
): SegmentWindow | null {
  const list = replay.windows.get(key);
  if (!list) return null;
  const target = Math.floor((ts - replay.windowSeconds) / replay.stepSeconds) * replay.stepSeconds;
  // Binary search for the last window_start at or before the target.
  let low = 0;
  let high = list.length - 1;
  let found = -1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (list[mid].windowStart <= target) {
      found = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  if (found < 0) return null;
  const candidate = list[found];
  // Only the window that actually covers the cursor counts. Anything older is a window the key
  // was not measurable in, and that absence is a fact about the detector, not missing data.
  return candidate.windowStart === target ? candidate : null;
}

/** The frame ordinal in force at sim time `ts`: the last frame at or before it. */
export function ordAt(replay: Replay, ts: number): number {
  const frames = replay.frames;
  let low = 0;
  let high = frames.length - 1;
  let found = -1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (frames[mid].ts <= ts) {
      found = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  return found;
}
