import type { IncidentSummary, Segment } from "./types";

/**
 * Severity, and how a rate compares to its own baseline.
 *
 * One place decides what colour a state gets, so the same status cannot be amber in one section
 * and red in another. The rule the palette encodes: red means an active failure or a refusal that
 * needs someone, amber means degraded or waiting on a human, blue is informational, green is
 * healthy. A number being large or important is not a severity and does not get a colour.
 */

export type Severity = "ok" | "warn" | "crit" | "info" | "idle";

export const SEVERITY_CLASS: Record<Severity, string> = {
  ok: "ok",
  warn: "warn",
  crit: "crit",
  info: "info",
  idle: "dim",
};

/**
 * Incident status to severity.
 *
 * `open` is an active failure nobody has taken yet, so it is the one that gets red. `escalated`
 * is amber: the agent stopped and a human owns it, which needs attention but is not the system
 * failing unattended. A planner error overrides both, because the agent did not choose to hand
 * that one over, it fell over.
 */
export function incidentSeverity(status: string, plannerFailed = false): Severity {
  if (plannerFailed) return "crit";
  switch (status) {
    case "open":
      return "crit";
    case "escalated":
    case "paused":
      return "warn";
    case "recovering":
      return "info";
    case "closed":
      return "ok";
    default:
      return "info";
  }
}

/** The success rate a segment is expected to hold. `baseline` on the wire is a failure rate. */
export function baselineSuccess(segment: Segment): number {
  return 1 - segment.baseline;
}

/** Signed deviation from the segment's own baseline, in percentage points. */
export function deviationPoints(segment: Segment): number {
  return (segment.rate - baselineSuccess(segment)) * 100;
}

/**
 * Severity for a deviation.
 *
 * The detector's own threshold is 0.15 absolute excess over baseline, so a segment 15 points down
 * is by definition the size of thing this system opens incidents for. Half of that is the warning
 * band. Anything shallower is inside the noise the detector was calibrated to ignore, and calling
 * it degraded on the dashboard would contradict the detector.
 *
 * The band between "inside the noise" and "above baseline" is deliberately neutral rather than
 * green. A segment sitting a tenth of a point under its baseline is not healthy news, it is no
 * news, and painting it green next to a downward arrow says two opposite things at once.
 */
export function deviationSeverity(points: number): Severity {
  if (points <= -15) return "crit";
  if (points <= -7.5) return "warn";
  if (points < 0.05) return "idle";
  return "ok";
}

/** The bar and the delta take the same colour, so the row never contradicts itself. */
export const SEVERITY_COLOUR: Record<Severity, string> = {
  ok: "var(--success)",
  warn: "var(--warning)",
  crit: "var(--danger)",
  info: "var(--accent)",
  idle: "var(--text-muted)",
};

/** `-14.7` to `"14.7 pt"`, with the direction carried by a caller-supplied arrow. */
export function formatPoints(points: number): string {
  return `${Math.abs(points).toFixed(1)} pt`;
}

export function deviationArrow(points: number): string {
  if (points <= -0.05) return "▾";
  if (points >= 0.05) return "▴";
  return "–";
}

/** Elapsed sim seconds rendered the way an on-call reads a duration. */
export function elapsed(fromTs: number, nowTs: number): string {
  const seconds = Math.max(0, nowTs - fromTs);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${String(minutes % 60).padStart(2, "0")}m`;
}

/**
 * A planner failure and a considered handover both end at ESCALATE_HUMAN and mean opposite
 * things, so the one that is a fault is identified from the ledger's own field rather than
 * guessed from the status.
 */
export function plannerErrorOf(
  timeline: { kind: string; payload: Record<string, unknown> }[],
  rationale: string | null | undefined,
): string | null {
  const planEntry = timeline.find((entry) => entry.kind === "decide.plan");
  const fromLedger = planEntry?.payload?.planner_error;
  if (typeof fromLedger === "string" && fromLedger.length > 0) return fromLedger;
  return rationale && rationale.startsWith("planner failed") ? rationale : null;
}

/**
 * Whether an escalation's own `reason` is a planner failure rather than a decision.
 *
 * `plannerErrorOf` above answers the same question for an incident, from the `decide.plan` entry.
 * An escalation carries only the reason string, and `_escalate` is called with the planner's error
 * verbatim when planning fails, so the prefix is the whole test. Both pages use one of these two so
 * they cannot disagree about what counts as a failure.
 */
export function isPlannerFailureReason(reason: string | null | undefined): boolean {
  return typeof reason === "string" && reason.startsWith("planner failed");
}

/** A baseline policy hangs its cases on a synthetic incident the detector never opened. */
export function realIncidents(incidents: IncidentSummary[]): IncidentSummary[] {
  return incidents.filter((incident) => !incident.id.endsWith("_baseline"));
}
