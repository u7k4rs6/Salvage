import { Link } from "react-router-dom";
import { shortHash, timeOnly } from "../../lib/format";
import type { LedgerPage } from "../../lib/types";

/**
 * Ledger activity: what the system actually did, in order, with the chain behind it.
 *
 * Read from the ledger rather than from the event stream. The SSE contract carries eleven event
 * names and most of them are notifications with an id in them; the ledger carries the record. The
 * stream is still what makes this live, in that an event arrives and this refetches.
 *
 * Every kind takes its stage's colour and always prints the stage word beside it, so colour is
 * never the only signal. Kinds with no stage, such as the simulator's own run markers, stay
 * neutral rather than being given a colour they have not earned.
 */

const STAGE: Record<string, { colour: string; stage: string }> = {
  "detect.incident.opened": { colour: "var(--crit)", stage: "detect" },
  "detect.incident.closed": { colour: "var(--ok)", stage: "detect" },
  "diagnose.reconciled": { colour: "var(--info)", stage: "diagnose" },
  "decide.plan": { colour: "var(--info)", stage: "plan" },
  "execute.action.executed": { colour: "var(--fg-2)", stage: "execute" },
  "execute.action.refused": { colour: "var(--crit)", stage: "gate" },
  "escalation.opened": { colour: "var(--warn)", stage: "escalate" },
  "escalation.decided": { colour: "var(--warn)", stage: "escalate" },
  "recovery.case.recovered": { colour: "var(--ok)", stage: "recover" },
};

export function Activity({ page, clock }: { page: LedgerPage; clock: string }) {
  const entries = [...page.entries].reverse();

  if (entries.length === 0) {
    return <p className="note px-2 py-3">Nothing has been written yet.</p>;
  }

  return (
    <div>
      <ol className="divide">
        {entries.map((entry) => {
          const stage = STAGE[entry.kind];
          return (
            <li
              key={entry.seq}
              className="row-hover grid grid-cols-[4rem_minmax(0,1fr)_auto] items-baseline gap-4 px-2 py-2"
            >
              <time className="mono note">{timeOnly(entry.ts)}</time>
              <div className="flex min-w-0 flex-wrap items-baseline gap-x-2.5">
                <span
                  aria-hidden="true"
                  className="dot self-center"
                  style={{ background: stage?.colour ?? "var(--fg-3)" }}
                />
                <span className="mono text-[13px]">{entry.kind}</span>
                {stage && <span className="lbl">{stage.stage}</span>}
                <span className="mono note truncate">{entry.ref_id}</span>
              </div>
              <span className="mono note" title={entry.hash}>
                {shortHash(entry.hash, 8)}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="note mt-3">
        Times on the {clock} clock.{" "}
        <Link to="/ledger" className="link focus-ring underline underline-offset-2">
          Full ledger, {page.total} entries
        </Link>
        . Hashes are the chain, not a display value.
      </p>
    </div>
  );
}
