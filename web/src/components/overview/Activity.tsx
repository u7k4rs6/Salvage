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
 * Mono is used for identifiers, hashes and the clock, and nothing else, because those are the
 * values a reader compares character by character.
 */

// Each ledger kind belongs to one stage of the pipeline and takes that stage's colour. The stage
// word is always printed beside it, so colour is never the only signal.
const STAGE: Record<string, { colour: string; stage: string }> = {
  "detect.incident.opened": { colour: "var(--incident)", stage: "detect" },
  "detect.incident.closed": { colour: "var(--recovered)", stage: "detect" },
  "diagnose.reconciled": { colour: "var(--diagnosis)", stage: "diagnose" },
  "decide.plan": { colour: "var(--diagnosis)", stage: "plan" },
  "execute.action.executed": { colour: "var(--text-2)", stage: "execute" },
  "execute.action.refused": { colour: "var(--incident)", stage: "gate" },
  "escalation.opened": { colour: "var(--pending)", stage: "escalate" },
  "escalation.decided": { colour: "var(--pending)", stage: "escalate" },
  "recovery.case.recovered": { colour: "var(--recovered)", stage: "recover" },
};

export function Activity({ page, clock }: { page: LedgerPage; clock: string }) {
  const entries = [...page.entries].reverse();

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-x-10 gap-y-4">
        <h2 className="display heading">Activity</h2>
        <Link to="/ledger" className="focus-ring microlabel microlabel-ink lift">
          Ledger &middot; {page.total} entries &rarr;
        </Link>
      </div>

      {entries.length === 0 ? (
        <p className="body-sm mt-6 pt-6" style={{ borderTop: "1px solid var(--hair-strong)" }}>
          Nothing has been written yet. Run a scenario.
        </p>
      ) : (
        <ol className="mt-6" style={{ borderTop: "1px solid var(--hair-strong)" }}>
          {entries.map((entry) => {
            const stage = STAGE[entry.kind];
            return (
              <li
                key={entry.seq}
                className="row-hover grid grid-cols-[4.5rem_1fr_auto] items-baseline gap-4 py-3"
                style={{ borderBottom: "1px solid var(--hair)" }}
              >
                <time className="mono" style={{ fontSize: 11, color: "var(--text-3)" }}>
                  {timeOnly(entry.ts)}
                </time>
                <div className="min-w-0">
                  <div className="flex items-baseline gap-2.5">
                    <span
                      aria-hidden="true"
                      className="inline-block h-1.5 w-1.5 shrink-0 rounded-full"
                      style={{ background: stage?.colour ?? "var(--text-3)" }}
                    />
                    <span className="mono" style={{ fontSize: 12.5, color: "var(--text)" }}>
                      {entry.kind}
                    </span>
                    {stage && <span className="microlabel">{stage.stage}</span>}
                  </div>
                  <div
                    className="mono truncate pl-4"
                    style={{ fontSize: 11, color: "var(--text-3)" }}
                  >
                    {entry.ref_id}
                  </div>
                </div>
                <div className="mono text-right" style={{ fontSize: 11, color: "var(--text-3)" }}>
                  {shortHash(entry.hash, 10)}
                </div>
              </li>
            );
          })}
        </ol>
      )}
      <p className="scope mt-4">
        Times on the {clock} clock. Hashes are the chain, not a display value.
      </p>
    </div>
  );
}
