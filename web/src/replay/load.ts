import s1Url from "../board/fixtures/s1_seed0.run.json?url";
import s2Url from "../board/fixtures/s2_seed1.run.json?url";
import s3Url from "../board/fixtures/s3_seed0.run.json?url";
import s4Url from "../board/fixtures/s4_seed0.run.json?url";
import { buildReplay, type Replay } from "./model";
import type { Recording } from "./types";

/**
 * The recordings this page can replay.
 *
 * Imported as URLs and fetched, not imported as modules. A recording is one and a half megabytes
 * of JSON, and S3's is four; bundling them would put every one in the first paint of every page
 * in the console and make the type checker walk their array literals for nothing. Only the
 * recording the visitor picks is fetched.
 *
 * One per fault scenario. Each is a real agent run whose planner answer came from the recorded
 * fixtures rather than a fallback, so every one reaches the executor with a model's plan: the
 * four are the four faults, not four picks from a longer list. S0 has no fault and so has no run
 * worth replaying.
 */

export interface ScenarioChoice {
  id: string;
  url: string;
  label: string;
  blurb: string;
}

export const SCENARIOS: ScenarioChoice[] = [
  {
    id: "s1_seed0",
    url: s1Url,
    label: "S1 seed 0, UPI handle outage",
    blurb: "Steered first, messaged second. 74 recoveries needed no message, 12 did.",
  },
  {
    id: "s2_seed1",
    url: s2Url,
    label: "S2 seed 1, card BIN authorisation failures",
    blurb: "Detect, diagnose, plan, gate, act, recover, close.",
  },
  {
    id: "s3_seed0",
    url: s3Url,
    label: "S3 seed 0, merchant-wide gateway degradation",
    blurb: "Escalated to a human, held every send, then sent once the gateway recovered.",
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
