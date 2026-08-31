import { Link } from "react-router-dom";
import { buildBoard, FLOOR_ATTEMPTS, type BoardGroup, type BoardNode } from "../../board/roster";
import {
  SEVERITY_CLASS,
  SEVERITY_COLOUR,
  baselineSuccess,
  deviationArrow,
  deviationPoints,
  deviationSeverity,
  formatPoints,
} from "../../lib/health";
import { count, percent } from "../../lib/format";
import type { Segment } from "../../lib/types";

/**
 * Payment health: which rail is degraded, then where inside it.
 *
 * Two levels, and the order is the point. The method summary answers "which payment path is
 * broken" in one glance across four rows. The segment table underneath answers "where inside it",
 * and it is the level the detector actually works at.
 *
 * Both levels use the same encoding: the bar runs from the segment's own baseline to where it is
 * now on a shared 0 to 100 axis, so its length is the excess and its direction is the sign. A
 * shared axis is what lets the eye run down the column and find the outlier without reading a
 * number. Green is only ever the direction, never a decoration.
 *
 * A segment the detector could not test is drawn as a dashed empty track rather than omitted.
 * `GET /api/overview` returns no row at all for a key below the 20-attempt floor, so without the
 * roster in board/roster.ts a below-floor key would be indistinguishable from an instrument that
 * does not exist. That distinction is a fact about the detector and it is kept on the page.
 */

const AXIS = [0, 25, 50, 75, 100];

function DeviationBar({ segment, small }: { segment: Segment; small?: boolean }) {
  const baseline = baselineSuccess(segment);
  const value = segment.rate;
  const worse = value < baseline;
  const left = Math.min(value, baseline);
  const width = Math.max(Math.abs(value - baseline), 0.002);
  const severity = deviationSeverity(deviationPoints(segment));

  return (
    <div
      className={`track${small ? " track-sm" : ""}`}
      role="img"
      aria-label={`${segment.instrument}: ${percent(value)} success against a ${percent(baseline)} baseline over ${segment.attempts} attempts`}
    >
      <div
        className="bar"
        style={{
          left: `${left * 100}%`,
          width: `${width * 100}%`,
          background: SEVERITY_COLOUR[severity],
          opacity: severity === "idle" ? 0.55 : worse ? 0.85 : 0.6,
        }}
      />
      <div className="baseline" style={{ left: `${baseline * 100}%` }} />
    </div>
  );
}

function Delta({ segment }: { segment: Segment }) {
  const points = deviationPoints(segment);
  const severity = deviationSeverity(points);
  return (
    <span className={`mono text-[12.5px] ${SEVERITY_CLASS[severity]}`}>
      {deviationArrow(points)} {formatPoints(points)}
    </span>
  );
}

/** The four rails, compact. This is the row that answers "which path is degraded". */
function MethodSummary({ board }: { board: ReturnType<typeof buildBoard> }) {
  return (
    <div className="divide">
      {board.methods.map((entry) => {
        const node = entry.methodNode;
        const measured = node && node.state === "measured" ? node.segment : null;
        return (
          <div
            key={entry.method}
            className="row-hover grid grid-cols-[6rem_minmax(0,1fr)_4.5rem_5rem_4rem] items-center gap-4 px-2 py-2.5"
          >
            <div className="text-[14px] font-medium uppercase tracking-[0.04em]">
              {entry.method}
            </div>
            {measured ? (
              <>
                <DeviationBar segment={measured} />
                <div className="fig-md text-right">{percent(measured.rate)}</div>
                <div className="text-right">
                  <Delta segment={measured} />
                </div>
                <div className="mono note text-right">n {count(measured.attempts)}</div>
              </>
            ) : (
              <>
                <div className="track">
                  <div className="track-empty" />
                </div>
                <div className="note text-right">below floor</div>
                <div className="note text-right">-</div>
                <div className="mono note text-right">n &lt; {FLOOR_ATTEMPTS}</div>
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}

function Lane({ node }: { node: BoardNode }) {
  if (node.state === "below_floor") {
    const peak = Math.round(node.roster.expected_attempts_peak_window);
    return (
      <div className="lane row-hover">
        <div className="mono note truncate">{node.instrument}</div>
        <div
          className="track"
          role="img"
          aria-label={`${node.instrument}: below the detection floor, about ${peak} attempts expected in a peak window against a floor of ${FLOOR_ATTEMPTS}`}
        >
          <div className="track-empty" />
        </div>
        <div className="note text-right">below floor</div>
        <div className="note text-right">-</div>
        <div className="mono note text-right">n &lt; {FLOOR_ATTEMPTS}</div>
      </div>
    );
  }

  const segment = node.segment;
  const inIncident = Boolean(segment.incident_id);
  const lane = (
    <div className="lane row-hover">
      <div className="flex items-center gap-2 truncate">
        {inIncident && (
          <span
            aria-hidden="true"
            className="inline-block h-2.5 w-[2px] flex-none"
            style={{ background: "var(--crit)" }}
          />
        )}
        <span className={`mono truncate text-[13px] ${inIncident ? "crit" : "mid"}`}>
          {node.instrument}
        </span>
      </div>
      <DeviationBar segment={segment} />
      <div className="fig-md text-right text-[14px]">{percent(segment.rate)}</div>
      <div className="text-right">
        <Delta segment={segment} />
      </div>
      <div className="mono note text-right">n {count(segment.attempts)}</div>
    </div>
  );

  return inIncident ? (
    <Link to={`/incidents/${segment.incident_id}`} className="focus-ring block">
      {lane}
    </Link>
  ) : (
    lane
  );
}

function Collapsed({ group }: { group: BoardGroup }) {
  const collapsed = group.collapsed;
  if (!collapsed) return null;
  return (
    <div className="grid grid-cols-[9.5rem_minmax(0,1fr)] items-baseline gap-4 px-2 py-1.5">
      <div className="mono note truncate">{group.title}</div>
      <div className="note">
        {collapsed.label}
        {collapsed.nodeCount > 0 && <span className="dim"> &middot; {collapsed.nodeCount} keys</span>}
      </div>
    </div>
  );
}

export function PaymentHealth({ segments }: { segments: Segment[] }) {
  const board = buildBoard(segments);

  return (
    <div>
      <MethodSummary board={board} />

      <div className="mt-6">
        <div className="lane border-b border-[color:var(--line)] pb-1.5">
          <div className="lbl">Segment</div>
          <div className="relative h-3">
            {AXIS.map((tick) => (
              <span
                key={tick}
                className="lbl absolute -top-0.5"
                style={{
                  left: `${tick}%`,
                  transform: tick === 100 ? "translateX(-100%)" : undefined,
                }}
              >
                {tick}
              </span>
            ))}
          </div>
          <div className="lbl text-right">Success</div>
          <div className="lbl text-right">Delta</div>
          <div className="lbl text-right">Volume</div>
        </div>

        {board.methods.map((entry) => (
          <section key={entry.method} className="mt-4">
            <div className="lbl lbl-2 px-2 pb-1">{entry.method}</div>
            {entry.groups.map((group) =>
              group.collapsed ? (
                <Collapsed key={group.id} group={group} />
              ) : (
                <div key={group.id} className="mb-2">
                  <div className="note px-2 pb-0.5 pl-4">{group.title}</div>
                  {group.nodes.map((node) => (
                    <Lane key={node.key} node={node} />
                  ))}
                </div>
              ),
            )}
          </section>
        ))}

        <p className="note mt-4">
          <span className="mono">{board.measured}</span> of{" "}
          <span className="mono">{board.total}</span> segments cleared the {FLOOR_ATTEMPTS}-attempt
          floor this window. Bars run from each segment&rsquo;s own baseline; length is the excess.
        </p>
      </div>
    </div>
  );
}
