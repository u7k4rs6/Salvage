import type { Frame } from "../../replay/model";
import { shortHash, timeOnly } from "../../lib/format";

/**
 * The last entries the replay has consumed, newest first.
 *
 * Frames read out of a table dump are marked, because they are not chain entries and a row that
 * looks identical to one would be overclaiming. Everything with a sequence number and a hash is in
 * the chain and the verify control covers it.
 */

const KIND_SEVERITY = (kind: string): string => {
  if (kind === "execute.action.refused") return "crit";
  if (kind === "detect.incident.opened") return "crit";
  if (kind === "escalation.opened") return "warn";
  if (kind === "execute.action.deferred" || kind === "execute.action.queued") return "warn";
  if (kind === "execute.link_paid" || kind === "execute.steer_recovered") return "ok";
  if (kind === "detect.incident.closed") return "ok";
  return "info";
};

export function Tail({ frames, currentOrd }: { frames: Frame[]; currentOrd: number }) {
  if (frames.length === 0) {
    return <p className="note">Nothing consumed yet.</p>;
  }
  return (
    <div className="panel divide">
      {frames.map((frame) => (
        <div
          key={`${frame.ord}`}
          className={`row-hover grid grid-cols-[4.5rem_5rem_minmax(0,1fr)_minmax(0,1fr)_6rem] items-baseline gap-3 px-3 py-2${
            frame.ord === currentOrd ? " held" : ""
          }`}
        >
          <span className="note mono">{timeOnly(frame.ts)}</span>
          <span className="note mono">{frame.seq === null ? "table" : `seq ${frame.seq}`}</span>
          <span className={`mono text-[length:var(--fs-meta)] ${KIND_SEVERITY(frame.kind)}`}>{frame.kind}</span>
          <span className="note mono truncate" title={frame.refId}>
            {frame.refId}
          </span>
          <span className="note mono text-right">
            {frame.hash ? shortHash(frame.hash, 10) : "not hashed"}
          </span>
        </div>
      ))}
    </div>
  );
}
