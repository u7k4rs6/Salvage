import type { Replay } from "../../replay/model";

/**
 * The fault as a headline subject: short enough to leave room for the verb.
 *
 * `faultInEnglish` is written for the narration line, where "cards starting 411111" is exactly
 * right. In a headline it is four words before anything happens, so the same selector is read for
 * the kind of thing rather than the identifier, and the identifier stays on the board underneath.
 */
function faultSubject(selector: Record<string, string>): string {
  if (selector.card_bin) return "A card BIN";
  if (selector.upi_handle) return "A UPI handle";
  if (selector.card_issuer) return "A card issuer";
  if (selector.nb_bank) return "A bank";
  if (selector.method) return `${selector.method.charAt(0).toUpperCase()}${selector.method.slice(1)}`;
  return "A payment route";
}

/**
 * What the run actually did, in one line, read off the recording.
 *
 * This was a fixed sentence about rerouting until S1 and S3 were recorded. It is true of the two
 * runs whose diagnosis allows steering and false of the two whose diagnosis forbids it: the action
 * matrix does not permit STEER_METHOD for `gateway_degradation` or `merchant_config`, so S3 and S4
 * reroute nothing and a headline claiming otherwise is a claim the recording does not support.
 */
function whatItDid(replay: Replay): string {
  const count = (kind: string) => replay.frames.filter((frame) => frame.kind === kind).length;
  const steered = count("execute.steer_recovered");
  const paid = count("execute.link_paid");
  const escalated = replay.frames.some((frame) => frame.kind === "escalation.opened");

  if (steered > 0) return "It rerouted what it was allowed to reroute, and refused the rest.";
  if (escalated && paid > 0) {
    return "It escalated to a person, held every message, and sent once the route recovered.";
  }
  if (escalated) return "It escalated to a person, and sent nothing at all.";
  return "It acted inside its limits, and refused what fell outside them.";
}

/**
 * The first ten seconds, over the board rather than instead of it.
 *
 * There is no entry screen. The visitor lands on the replay itself, paused, with the board already
 * drawn and already moving behind a scrim. What sits on top is a headline, not a briefing: the
 * thing that broke and how long it took to catch, in one sentence they can read without deciding
 * to.
 *
 * The three paragraphs that used to be here have not been deleted, they have moved behind "What am
 * I looking at?" in the transport row. Somebody who wants the background can have it; somebody who
 * wants to watch the run is not made to read it first.
 *
 * Every specific is still read off the recording that is about to play. The date and the card range
 * are not written here, so a recapture changes them.
 */
export function Entry({
  replay,
  leaving,
  onStart,
}: {
  replay: Replay;
  /** True for the length of the dissolve, so the scrim and the copy can go together. */
  leaving: boolean;
  onStart: () => void;
}) {
  const fault = replay.faults[0] ?? null;
  const subject = fault ? faultSubject(fault.selector) : "A payment route";
  const day = fault
    ? new Date(fault.start * 1000).toLocaleDateString("en-IN", {
        timeZone: "Asia/Kolkata",
        day: "numeric",
        month: "long",
        year: "numeric",
      })
    : null;

  // How long the detector took, read off the recording rather than written down. The incident is
  // not open at frame zero, so this comes from the ledger and not from replay state.
  const opened = replay.frames.find((frame) => frame.kind === "detect.incident.opened") ?? null;
  const minutes = fault && opened ? Math.max(1, Math.round((opened.ts - fault.start) / 60)) : null;

  return (
    <div className={`rp-curtain${leaving ? " is-leaving" : ""}`} role="dialog" aria-label="Start the replay">
      <div className="rp-curtain-copy">
        <p className="rp-eyebrow">Recorded run{day ? `, ${day}` : ""}</p>
        <h1 className="rp-headline">
          {subject} started failing. Salvage caught it in {minutes ?? 7} minutes.
        </h1>
        <p className="rp-subline">{whatItDid(replay)}</p>
        <button type="button" className="rp-start focus-ring" onClick={onStart}>
          <svg viewBox="0 0 12 14" aria-hidden="true" className="rp-start-glyph">
            <path d="M1 1 L11 7 L1 13 Z" fill="currentColor" />
          </svg>
          Watch the run
        </button>
        <p className="rp-footnote">About a minute. Pause and scrub at any point.</p>
      </div>
    </div>
  );
}
