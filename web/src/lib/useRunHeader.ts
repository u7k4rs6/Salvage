import { useMemo } from "react";
import { useApi } from "./useApi";
import type { LedgerPage } from "./types";

/**
 * The run the current world came from, read out of the ledger rather than out of process memory.
 *
 * `GET /api/sim/status` also carries a scenario, but it is in-process state on the API: restart
 * the server and it is null while the database still holds a finished world. The ledger's first
 * entry is durable, so it is what the page reads.
 *
 * The payload is written by the simulator and carries the scenario id, the seed, the variant and
 * the fault windows it injected, with the selector for each. That is the only place the console
 * can learn when a fault actually started, which is what makes time to detect a real number here
 * rather than an assertion. It does not carry `truth_cause`, and this deliberately does not go
 * looking for one: the agent's diagnosis is the thing being measured, and printing the answer
 * beside it would make the page a worse instrument.
 */

export interface InjectedFault {
  start_ts: number;
  end_ts: number;
  /** `{method: "upi", upi_handle: "okhdfcbank"}`, or `{}` for a fault across every method. */
  selector: Record<string, string>;
}

export interface RunHeader {
  runId: string;
  scenario: string;
  seed: number | null;
  variant: string | null;
  faults: InjectedFault[];
}

function describeSelector(selector: Record<string, string>): string {
  const parts = Object.entries(selector).map(([, value]) => value);
  return parts.length === 0 ? "all methods" : parts.join(" / ");
}

export function selectorLabel(fault: InjectedFault): string {
  return describeSelector(fault.selector);
}

export function useRunHeader(): RunHeader | null {
  const state = useApi<LedgerPage>("/api/ledger?kind=sim.run.started&limit=1");

  return useMemo(() => {
    const entry = state.data?.entries?.[0];
    if (!entry) return null;
    const payload = entry.payload as Record<string, unknown>;
    const scenario = payload.scenario;
    if (typeof scenario !== "string") return null;

    const rawFaults = Array.isArray(payload.faults) ? payload.faults : [];
    const faults: InjectedFault[] = rawFaults.flatMap((raw) => {
      const fault = raw as Record<string, unknown>;
      const start = fault.start_ts;
      const end = fault.end_ts;
      if (typeof start !== "number" || typeof end !== "number") return [];
      const selector =
        fault.selector && typeof fault.selector === "object"
          ? (fault.selector as Record<string, string>)
          : {};
      return [{ start_ts: start, end_ts: end, selector }];
    });

    return {
      runId: entry.ref_id,
      scenario,
      seed: typeof payload.seed === "number" ? payload.seed : null,
      variant: typeof payload.variant === "string" ? payload.variant : null,
      faults,
    };
  }, [state.data]);
}

/**
 * The injected fault an incident corresponds to, or null.
 *
 * Matched on the selector's values appearing in the segment key, which is what makes
 * `{method: "upi", upi_handle: "okhdfcbank"}` line up with `upi:upi_handle:okhdfcbank`. A fault
 * with an empty selector spans every method and matches anything, which is how S3 is written.
 * The window has to contain the moment the incident opened, so a second fault later in the day
 * cannot claim an earlier detection.
 */
export function faultForIncident(
  run: RunHeader | null,
  incident: { segment_key: string; opened_at: number },
): InjectedFault | null {
  if (!run) return null;
  const candidates = run.faults.filter((fault) => fault.start_ts <= incident.opened_at);
  const scoped = candidates.filter((fault) => {
    const values = Object.values(fault.selector);
    if (values.length === 0) return true;
    return values.every((value) => incident.segment_key.includes(value));
  });
  const pool = scoped.length > 0 ? scoped : [];
  if (pool.length === 0) return null;
  // The latest fault that had already started is the one this incident can be attributed to.
  return pool.reduce((best, fault) => (fault.start_ts > best.start_ts ? fault : best));
}
