/**
 * The board tile as the Overview shipped it before the redesign.
 *
 * It is kept because `pages/Specimens.tsx` renders it: the specimen sheet exists to show real
 * components rather than copies of them. The redesigned Overview draws segments as deviation
 * lanes instead, so nothing else imports this.
 */
import { Link } from "react-router-dom";
import { FLOOR_ATTEMPTS, type BoardGroup, type BoardNode } from "../../board/roster";
import { percent, segmentLabel } from "../../lib/format";
import type { Segment } from "../../lib/types";

/**
 * Neutral to red on the failure rate. Five steps, because a continuous gradient reads as noise on
 * a dense grid and an ops console is scanned, not admired.
 */
function cellColour(segment: Segment): string {
  const excess = segment.failure_rate - segment.baseline;
  if (segment.attempts === 0) return "bg-neutral-50 text-neutral-400";
  if (excess >= 0.3) return "bg-red-600 text-white";
  if (excess >= 0.15) return "bg-red-400 text-white";
  if (excess >= 0.07) return "bg-red-200 text-red-900";
  if (excess >= 0.03) return "bg-amber-100 text-amber-900";
  return "bg-neutral-100 text-neutral-700";
}

/**
 * A tile is measured or it is below the detection floor. The second state is not an error and not
 * a loading state: the detector needs 20 attempts in a 15-minute window before a key can be
 * tested at all, and most instruments are under that line for most of the day. The node stays on
 * the board because its absence from measurement is the thing worth seeing.
 */
// Exported for web/src/pages/Specimens.tsx. The specimen sheet renders the real tile rather
// than a copy of it, so the two cannot drift apart. Export only: nothing here changed.
export function Cell({ node }: { node: BoardNode }) {
  if (node.state === "below_floor") {
    const peak = node.roster.expected_attempts_peak_window;
    // A node sitting near the floor is not reliably absent, it flips window to window on
    // ordinary noise. Saying so is better than implying the board has a fixed shape.
    const marginal = node.roster.marginal_at_peak
      ? " Sits close enough to the floor to appear in some windows and not others."
      : "";
    return (
      <div
        aria-label={`${node.instrument}, below the detection floor, no rate measured this window. About ${peak} attempts expected in a peak window against a floor of ${FLOOR_ATTEMPTS}.${marginal}`}
        title={`About ${peak} attempts expected in a peak 15-minute window. Floor is ${FLOOR_ATTEMPTS}.${marginal}`}
        className="h-full border border-dashed border-neutral-300 bg-neutral-50 px-2 py-1.5 text-neutral-400"
      >
        <div className="truncate text-[length:var(--fs-micro)] font-medium">{node.instrument}</div>
        <div className="text-[length:var(--fs-micro)] leading-tight">below detection floor</div>
      </div>
    );
  }

  const segment = node.segment;
  const inner = (
    <div
      // baseline arrives as a failure rate; every number on this cell is a success rate, so it
      // is converted here rather than leaving two conventions on one tile.
      aria-label={`${segmentLabel(segment.key)}, success rate ${percent(segment.rate)}, baseline success rate ${percent(1 - segment.baseline)}, ${segment.attempts} attempts${segment.incident_id ? ", inside an open incident" : ""}`}
      className={`h-full border ${
        segment.incident_id ? "border-2 border-red-600" : "border-neutral-200"
      } ${cellColour(segment)} px-2 py-1.5`}
    >
      <div className="truncate text-[length:var(--fs-micro)] font-medium">{segment.instrument}</div>
      <div className="num text-[length:var(--fs-meta)] font-semibold">{percent(segment.rate)}</div>
      <div className="num text-[length:var(--fs-micro)] opacity-80">
        base {percent(1 - segment.baseline)} / n {segment.attempts}
      </div>
      {segment.incident_id && <div className="mt-0.5 text-[length:var(--fs-micro)] font-semibold">incident</div>}
    </div>
  );
  return segment.incident_id ? (
    <Link to={`/incidents/${segment.incident_id}`} className="block h-full">
      {inner}
    </Link>
  ) : (
    inner
  );
}

/** A whole dimension folded into one row, because five empty tiles say less than one sentence. */
export function CollapsedGroup({ group }: { group: BoardGroup }) {
  const collapsed = group.collapsed;
  if (!collapsed) return null;
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 border border-dashed border-neutral-300 bg-neutral-50 px-2 py-1.5">
      <span className="text-[length:var(--fs-micro)] font-medium text-neutral-500">{group.title}</span>
      <span className="text-[length:var(--fs-micro)] text-neutral-500">{collapsed.label}</span>
      <span className="text-[length:var(--fs-micro)] text-neutral-400">{collapsed.detail}</span>
    </div>
  );
}

