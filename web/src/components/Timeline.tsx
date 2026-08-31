import { Badge, Disclosure, Code } from "./primitives";
import { timeOnly, shortHash, rupees } from "../lib/format";
import type { LedgerEntry } from "../lib/types";

// Ledger kinds carry meaning, so the colour follows the kind rather than being decorative.
function toneFor(kind: string): "neutral" | "danger" | "warning" | "success" | "accent" {
  if (kind.includes("refused") || kind.includes("closed")) return "neutral";
  if (kind.startsWith("detect.incident.opened")) return "danger";
  if (kind.startsWith("escalation")) return "warning";
  if (kind.includes("link_paid") || kind.includes("recovered")) return "success";
  return "accent";
}

/** One-line summaries. A timeline that shows raw JSON by default is not a timeline. */
/**
 * One line describing a ledger entry, read from that entry's own payload.
 *
 * Seven of these cases were reading keys the writer does not emit, so the ledger showed
 * "undefined at confidence 0.95" for every diagnosis, "0 action(s) proposed" for every plan, and
 * "order undefined" for every recovery. The key names below are checked against what
 * `salvage/` actually appends, kind by kind.
 */
export function summarise(entry: LedgerEntry): string {
  const payload = (entry.payload || {}) as Record<string, any>;
  const value = (key: string) => payload[key];

  /** The first gate that failed, which is the rule that decided the outcome. */
  const decidingRule = (): string | null => {
    const gates = value("gates");
    if (!Array.isArray(gates)) return null;
    const failed = gates.find((gate: any) => gate && gate.passed === false);
    return failed?.rule ?? null;
  };

  switch (entry.kind) {
    case "sim.run.started":
      return `scenario ${value("scenario")} seed ${value("seed")}`;
    case "sim.run.finished":
      return `${value("attempts")} attempts, stream digest ${shortHash(
        String(value("stream_digest") ?? ""),
      )}`;
    case "detect.incident.opened":
      return `${value("segment_key")} opened, ${rupees(value("at_risk_amount"))} at risk`;
    case "detect.incident.closed":
      return `${value("segment_key")} recovered`;
    case "detect.incident.resegmented":
      return `attributed to ${value("to") ?? value("segment_key")}`;
    case "diagnose.reconciled":
      return `${String(value("root_cause") ?? "unknown").replace(/_/g, " ")} at confidence ${value(
        "confidence",
      )}`;
    case "decide.plan": {
      const actions = value("plan")?.actions;
      const count = Array.isArray(actions) ? actions.length : 0;
      const failure = value("planner_error");
      if (failure) return "planner failed, escalating";
      return `${count} action${count === 1 ? "" : "s"} proposed`;
    }
    case "execute.action.executed":
      return `${value("type")} executed`;
    case "execute.action.refused":
      return `${value("type")} refused: ${decidingRule() ?? "policy"}`;
    case "execute.action.deferred":
      return `${value("type")} deferred: ${decidingRule() ?? "timing"}`;
    case "execute.action.queued":
      return `${value("type")} queued: ${decidingRule() ?? "quiet hours"}`;
    case "execute.link_paid":
      return `link paid, ${rupees(value("amount"))}`;
    case "execute.steer_recovered":
      return `recovered by steer, ${rupees(value("amount"))}`;
    case "channel.opt_out":
      return "customer opted out";
    case "escalation.opened":
      return `${value("reason")}`;
    case "escalation.decided":
      return `${value("decision")}`;
    case "control.kill_switch":
      return value("enabled") ? "outbound actions suspended" : "outbound actions resumed";
    case "webhook.received":
      return `${value("event_type")}${value("verified") === false ? ", unverified" : ""}`;
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
        <li key={check.rule} className="num text-[length:var(--fs-micro)]">
          <span className={check.passed ? "text-[color:var(--success)]" : "text-[color:var(--danger)]"}>
            {check.passed ? "pass" : "fail"}
          </span>{" "}
          <span className="text-[color:var(--text-primary)]">{check.rule}</span>
          <span className="text-[color:var(--text-muted)]"> {check.detail}</span>
        </li>
      ))}
    </ul>
  );
}

export function Timeline({ entries }: { entries: LedgerEntry[] }) {
  return (
    <ol className="divide-y divide-[color:var(--border)]">
      {entries.map((entry) => (
        <li key={entry.seq} className="py-2">
          <div className="flex items-baseline gap-2">
            <span className="num w-10 shrink-0 text-right text-[length:var(--fs-meta)] text-[color:var(--text-muted)]">
              {entry.seq}
            </span>
            <span className="num w-20 shrink-0 text-[length:var(--fs-meta)] text-[color:var(--text-secondary)]">{timeOnly(entry.ts)}</span>
            <Badge tone={toneFor(entry.kind)}>{entry.kind}</Badge>
            <span className="text-[length:var(--fs-meta)] text-[color:var(--text-primary)]">{summarise(entry)}</span>
          </div>
          <div className="ml-32">
            <Gates payload={entry.payload} />
            <Disclosure summary="payload" className="mt-1">
              <Code>{JSON.stringify(entry.payload, null, 2)}</Code>
              <div className="num mt-1 text-[length:var(--fs-micro)] text-[color:var(--text-muted)]">
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
