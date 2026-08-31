import s2Url from "../board/fixtures/s2_seed1.run.json?url";
import s4Url from "../board/fixtures/s4_seed0.run.json?url";
import { buildReplay, type Replay } from "./model";
import type { Recording } from "./types";

/**
 * The recordings this page can replay.
 *
 * Imported as URLs and fetched, not imported as modules. A recording is one and a half megabytes
 * of JSON; bundling it would put it in the first paint of every page in the console and make the
 * type checker walk nineteen thousand array literals for nothing.
 *
 * Two of them, because between them they hold both terminal outcomes. S2 seed 1 runs the whole
 * arc through to recovery. S4 seed 0 diagnoses a merchant-side cause, which the action matrix
 * forbids contacting customers about, and stops at a human. There are only two because those are
 * the runs the recorded planner fixtures cover; the note in docs/BUILD_LOG.md says why.
 */

export interface ScenarioChoice {
  id: string;
  url: string;
  label: string;
  blurb: string;
}

export const SCENARIOS: ScenarioChoice[] = [
  {
    id: "s2_seed1",
    url: s2Url,
    label: "S2 seed 1, card BIN authorisation failures",
    blurb: "Detect, diagnose, plan, gate, act, recover, close.",
  },
  {
    id: "s4_seed0",
    url: s4Url,
    label: "S4 seed 0, merchant misconfiguration",
    blurb: "Diagnosed merchant-side, so nothing customer-facing. Ends at a human.",
  },
];

const cache = new Map<string, Replay>();

export async function loadReplay(choice: ScenarioChoice): Promise<Replay> {
  const cached = cache.get(choice.id);
  if (cached) return cached;
  const response = await fetch(choice.url);
  if (!response.ok) {
    throw new Error(`${choice.url}: ${response.status} ${response.statusText}`);
  }
  const recording = (await response.json()) as Recording;
  if (recording.meta?.artifact !== "salvage.run.recording") {
    throw new Error(`${choice.url} is not a salvage.run.recording`);
  }
  const replay = buildReplay(recording);
  cache.set(choice.id, replay);
  return replay;
}
