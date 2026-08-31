import { Badge, Disclosure, Code } from "./primitives";
import { timeOnly, shortHash } from "../lib/format";
import type { LedgerEntry } from "../lib/types";

// Ledger kinds carry meaning, so the colour follows the kind rather than being decorative.
function toneFor(kind: string): "neutral" | "red" | "amber" | "green" | "accent" {
  if (kind.includes("refused") || kind.includes("closed")) return "neutral";
  if (kind.startsWith("detect.incident.opened")) return "red";
  if (kind.startsWith("escalation")) return "amber";
  if (kind.includes("link_paid") || kind.includes("recovered")) return "green";
  return "accent";
}

/** One-line summaries. A timeline that shows raw JSON by default is not a timeline. */
export function summarise(entry: LedgerEntry): string {
  const payload = entry.payload || {};
  const value = (key: string) => payload[key];
  switch (entry.kind) {
    case "sim.run.started":
      return `scenario ${value("scenario")} seed ${value("seed")}`;
    case "sim.run.finished":
      return `${value("attempts")} attempts, stream digest ${shortHash(
        String(value("stream_digest") ?? ""),
      )}`;
    case "detect.incident.opened":
      return `${value("segment_key")}`;
    case "detect.incident.closed":
      return `${value("segment_key")} closed`;
    case "detect.incident.resegmented":
      return `attributed to ${value("segment_key")}`;
    case "diagnose.reconciled":
      return `${value("reconciled")} at confidence ${value("confidence")}`;
    case "decide.plan":
      return `${(value("actions") as unknown[])?.length ?? 0} action(s) proposed`;
    case "execute.action.executed":
      return `${value("type")} executed`;
    case "execute.action.refused":
      return `${value("type")} refused: ${value("rule") ?? "policy"}`;
    case "execute.action.deferred":
      return `${value("type")} deferred: ${value("rule") ?? "timing"}`;
    case "execute.action.queued":
      return `${value("type")} queued`;
    case "execute.link_paid":
      return `link paid, order ${value("order_id")}`;
    case "execute.steer_recovered":
      return `recovered by steer, order ${value("order_id")}`;
    case "channel.opt_out":
      return "customer opted out";
    case "escalation.opened":
      return `${value("reason")}`;
    case "escalation.decided":
      return `${value("decision")}`;
    case "control.kill_switch":
      return value("enabled") ? "outbound actions suspended" : "outbound actions resumed";
    case "webhook.received":
      return `${value("event")} ${value("event_id") ?? ""}`;
    default:
      return "";
  }
}

/** Gate evaluations render as a compact pass/fail list rather than a payload (spec 4.2). */
function Gates({ payload }: { payload: Record<string, unknown> }) {
  const gate = payload.gate as { rule: string; passed: boolean; detail: string }[] | undefined;
  if (!gate || !Array.isArray(gate)) return null;
  return (
    <ul className="mt-1 space-y-0.5">
      {gate.map((check) => (
        <li key={check.rule} className="num text-[12.5px]">
          <span className={check.passed ? "text-[color:var(--ok)]" : "text-[color:var(--crit)]"}>
            {check.passed ? "pass" : "fail"}
          </span>{" "}
          <span className="text-[color:var(--fg)]">{check.rule}</span>
          <span className="text-[color:var(--fg-3)]"> {check.detail}</span>
        </li>
      ))}
    </ul>
  );
}

export function Timeline({ entries }: { entries: LedgerEntry[] }) {
  return (
    <ol className="divide-y divide-[color:var(--line)]">
      {entries.map((entry) => (
        <li key={entry.seq} className="py-2">
          <div className="flex items-baseline gap-2">
            <span className="num w-10 shrink-0 text-right text-[13px] text-[color:var(--fg-3)]">
              {entry.seq}
            </span>
            <span className="num w-20 shrink-0 text-[13px] text-[color:var(--fg-2)]">{timeOnly(entry.ts)}</span>
            <Badge tone={toneFor(entry.kind)}>{entry.kind}</Badge>
            <span className="text-[13px] text-[color:var(--fg)]">{summarise(entry)}</span>
          </div>
          <div className="ml-32">
            <Gates payload={entry.payload} />
            <Disclosure summary="payload" className="mt-1">
              <Code>{JSON.stringify(entry.payload, null, 2)}</Code>
              <div className="num mt-1 text-[12.5px] text-[color:var(--fg-3)]">
                hash {shortHash(entry.hash)}
                {entry.prev_hash ? ` after ${shortHash(entry.prev_hash)}` : ""}
              </div>
            </Disclosure>
          </div>
        </li>
      ))}
    </ol>
  );
}
