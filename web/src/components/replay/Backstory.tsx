import type { Replay } from "../../replay/model";
import { faultInEnglish } from "../../replay/narrate";
import { count } from "../../lib/format";

/**
 * Where the entry copy went.
 *
 * Three paragraphs used to stand between the visitor and the run: what broke, what Salvage does,
 * and that this is a recording rather than a mock-up. All three are still true and still worth
 * reading, so none of them was cut. They sit behind a disclosure in the transport row instead,
 * which puts them in front of the person who wants them and out of the way of the person who does
 * not.
 *
 * A disclosure rather than a modal because nothing here needs acknowledging. It opens in place,
 * closes with the same control, and the run keeps playing behind it.
 */
export function Backstory({ replay }: { replay: Replay }) {
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
    <details className="rp-backstory">
      <summary className="rp-backstory-summary focus-ring">What am I looking at?</summary>
      <div className="rp-backstory-body">
        <p>
          <strong className="rp-backstory-strong">What broke.</strong> On {when}, {thing} stopped
          going through. The bank that issues them started turning them down at the moment it checks
          the payment is genuine. Shoppers saw a failure and most of them did not try again.
        </p>
        <p>
          <strong className="rp-backstory-strong">What Salvage does.</strong> It watches every
          payment attempt and learns what normal looks like for each kind. When one kind starts
          failing far more than its own normal, it says so, works out why, and decides what it is
          allowed to do about it. Then it acts, inside limits it cannot talk itself out of, and
          writes down every step in a record that cannot be edited afterwards.
        </p>
        <p>
          <strong className="rp-backstory-strong">What you are watching.</strong> Not a mock-up. A
          real run of that simulated world, recorded once and replayed here from its own log:{" "}
          {count(replay.recording.ledger.length)} entries, in the order they were written, at
          whatever speed you choose. Every number on the screen comes out of that log. Where the run
          did not record something, the page shows nothing rather than a guess.
        </p>
      </div>
    </details>
  );
}
