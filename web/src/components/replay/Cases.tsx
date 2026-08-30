import type { ReplayState } from "../../replay/state";
import { count, rupeesShort } from "../../lib/format";

/**
 * The case board: how many recovery cases are in each state right now.
 *
 * Where a state comes from is marked, because the two sources are not equally strong. DETECTED,
 * DEFERRED and WAITING are read off the chain: the `case.not_terminal` gate on every evaluated
 * action carries the case's state at that moment, and an executed send moves it to WAITING.
 * RECOVERED and OPTED_OUT are chain entries in their own right.
 *
 * ABANDONED and PAID_ELSEWHERE are not in the chain at all. The scheduler moves a case into them
 * without writing an entry, so they come from `recovery_cases.updated_at` in the recording, which
 * is the moment of the last transition. That is recorded data, but it is a table read and not a
 * hashed entry, and the board says so rather than letting the two look alike.
 */

const CHAINED = new Set(["DETECTED", "ELIGIBLE", "DEFERRED", "LINK_CREATED", "NUDGED", "WAITING", "RECOVERED", "OPTED_OUT"]);

const STATE_SEVERITY: Record<string, string> = {
  RECOVERED: "ok",
  WAITING: "info",
  DEFERRED: "warn",
  OPTED_OUT: "warn",
  ABANDONED: "dim",
  PAID_ELSEWHERE: "dim",
};

export function Cases({ state }: { state: ReplayState }) {
  const tracked = state.cases.size;

  return (
    <div>
      <div className="board">
        {state.caseCounts.map((entry) => (
          <div key={entry.state} className="cell">
            <div className={`lbl ${STATE_SEVERITY[entry.state] ?? ""}`}>{entry.state}</div>
            <div className="fig-lg mt-1">{count(entry.count)}</div>
            <div className="note mt-1">{CHAINED.has(entry.state) ? "from the chain" : "from the case table"}</div>
          </div>
        ))}
        {state.caseCounts.length === 0 && (
          <div className="cell">
            <div className="lbl">No cases</div>
            <div className="note mt-1">Nothing has been opened against this incident yet.</div>
          </div>
        )}
      </div>

      <div className="board mt-4">
        <div className="cell">
          <div className="lbl">Links created</div>
          <div className="fig-lg mt-1">{count(state.linksCreated)}</div>
          <div className="note mt-1">first executed send per case</div>
        </div>
        <div className="cell">
          <div className="lbl ok">Recovered by link</div>
          <div className="fig-lg mt-1">{count(state.recoveredByLink)}</div>
          <div className="note mt-1">execute.link_paid</div>
        </div>
        <div className="cell">
          <div className="lbl ok">Recovered by steer</div>
          <div className="fig-lg mt-1">{count(state.recoveredBySteer)}</div>
          <div className="note mt-1">execute.steer_recovered</div>
        </div>
        <div className="cell">
          <div className="lbl">Recovered value</div>
          <div className="fig-lg mt-1">{rupeesShort(state.recoveredAmount)}</div>
          <div className="note mt-1">link and steer only</div>
        </div>
        <div className="cell">
          <div className="lbl warn">Opt-outs</div>
          <div className="fig-lg mt-1">{count(state.optOuts)}</div>
          <div className="note mt-1">channel.opt_out</div>
        </div>
      </div>

      <p className="note mt-3">
        {count(tracked)} case{tracked === 1 ? "" : "s"} have moved so far. Only link and steer are
        counted here: they are the two routes the agent caused and the only two the chain records.
        Organic recovery is a comparison against a baseline, and it belongs on Results.
      </p>
    </div>
  );
}
