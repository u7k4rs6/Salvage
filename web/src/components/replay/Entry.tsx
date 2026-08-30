import type { Replay } from "../../replay/model";
import { faultInEnglish } from "../../replay/narrate";
import { count } from "../../lib/format";

/**
 * The first thirty seconds.
 *
 * A visitor arrives knowing nothing about payments in India, about Razorpay, or about what this
 * project claims. Before any data, three sentences: what broke, what the system does about it, and
 * what they are about to watch. Then one button.
 *
 * It is one screen and not a tour, because a tour is a thing to be dismissed and this is a thing to
 * be read. It does not come back once the run starts: a visitor who has pressed the button has
 * already been told, and an explainer that reappears is an explainer that gets in the way.
 *
 * Every specific in it is read off the recording that is about to play. The date, the time, the
 * card range and the number of entries are not written here; if the recording is recaptured they
 * change with it.
 */
export function Entry({ replay, onStart }: { replay: Replay; onStart: () => void }) {
  const fault = replay.faults[0] ?? null;
  const thing = fault ? faultInEnglish(fault.selector) : "payments";
  const when = fault
    ? new Date(fault.start * 1000).toLocaleString("en-IN", {
        timeZone: "Asia/Kolkata",
        day: "numeric",
        month: "long",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      })
    : null;

  return (
    <div className="entry">
      <div className="entry-inner">
        <div className="lbl">Salvage</div>
        <h1 className="entry-title mt-3">
          When a payment fails, the sale is usually just gone.
        </h1>

        <div className="entry-body mt-6">
          <p>
            <strong className="entry-strong">What broke.</strong> On {when}, {thing} stopped going
            through. The bank that issues them started turning them down at the moment it checks the
            payment is genuine. Shoppers saw a failure and most of them did not try again.
          </p>
          <p className="mt-4">
            <strong className="entry-strong">What Salvage does.</strong> It watches every payment
            attempt and learns what normal looks like for each kind. When one kind starts failing
            far more than its own normal, it says so, works out why, and decides what it is allowed
            to do about it. Then it acts, inside limits it cannot talk itself out of, and writes
            down every step in a record that cannot be edited afterwards.
          </p>
          <p className="mt-4">
            <strong className="entry-strong">What you are about to watch.</strong> Not a mock-up. A
            real run of that simulated world, recorded once and replayed here from its own log:{" "}
            {count(replay.recording.ledger.length)} entries, in the order they were written, at
            whatever speed you choose. Every number on the screen comes out of that log. Where the
            run did not record something, the page shows nothing rather than a guess.
          </p>
        </div>

        <button type="button" className="entry-button focus-ring mt-8" onClick={onStart}>
          Watch the run
        </button>
        <p className="note mt-4">
          Takes about a minute. You can pause, step and scrub at any point.
        </p>
      </div>
    </div>
  );
}
