import { Link } from "react-router-dom";
import { shortHash, timeOnly } from "../../lib/format";
import type { LedgerPage } from "../../lib/types";

/**
 * System activity, read from the ledger rather than from the event stream.
 *
 * The SSE contract carries eleven event names and most of them are notifications with an id in
 * them. The ledger carries what actually happened, in order, with the chain behind it. The stream
 * is still what makes this live: an event arrives, this refetches.
 *
 * Monospace is used for identifiers, hashes and the clock, and nothing else, because those are
 * the values a reader compares character by character.
 */

// Each ledger kind belongs to one stage of the pipeline and takes that stage's colour. The stage
// word is always printed beside it, so colour is never the only signal.
const STAGE: Record<string, { colour: string; stage: string }> = {
  "detect.incident.opened": { colour: "var(--detect)", stage: "detect" },
  "detect.incident.closed": { colour: "var(--detect)", stage: "detect" },
  "diagnose.reconciled": { colour: "var(--diagnose)", stage: "diagnose" },
  "decide.plan": { colour: "var(--diagnose)", stage: "plan" },
  "execute.action.executed": { colour: "var(--execute)", stage: "execute" },
  "execute.action.refused": { colour: "var(--gate)", stage: "gate" },
  "escalation.opened": { colour: "var(--escalate)", stage: "escalate" },
  "escalation.decided": { colour: "var(--escalate)", stage: "escalate" },
  "recovery.case.recovered": { colour: "var(--recover)", stage: "recover" },
};

export function Activity({ page, clock }: { page: LedgerPage; clock: string }) {
  const entries = [...page.entries].reverse();

  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="display text-[clamp(1.25rem,1.8vw,1.6rem)]">Activity</h2>
        <Link to="/ledger" className="focus-ring label label-ink hover:text-[color:var(--ink)]">
          ledger &middot; {page.total} entries
        </Link>
      </div>

      {entries.length === 0 ? (
        <p className="rule-strong mt-3 pt-3 text-[12.5px] text-[color:var(--ink-2)]">
          Nothing has been written yet. Run a scenario.
        </p>
      ) : (
        <ol className="rule-strong mt-3 pt-1">
          {entries.map((entry) => {
            const stage = STAGE[entry.kind];
            return (
              <li
                key={entry.seq}
                className="rule row-hover grid grid-cols-[3.5rem_1fr] gap-3 px-2 py-2"
              >
                <time className="num pt-px text-[11px] text-[color:var(--ink-3)]">
                  {timeOnly(entry.ts)}
                </time>
                <div className="min-w-0">
                  <div className="flex items-baseline gap-2">
                    <span
                      aria-hidden="true"
                      className="inline-block h-1.5 w-1.5 shrink-0 rounded-full"
                      style={{ background: stage?.colour ?? "var(--ink-3)" }}
                    />
                    <span className="text-[12.5px] font-medium">{entry.kind}</span>
                    {stage && <span className="label">{stage.stage}</span>}
                  </div>
                  <div className="num truncate pl-3.5 text-[11px] text-[color:var(--ink-3)]">
                    {entry.ref_id} &middot; {shortHash(entry.hash, 10)}
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      )}
      <p className="mt-2 px-2 text-[11px] text-[color:var(--ink-3)]">
        Times on the {clock} clock. Hashes are the chain, not a display value.
      </p>
    </div>
  );
}
