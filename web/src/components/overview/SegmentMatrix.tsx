import { Link } from "react-router-dom";
import { buildBoard, FLOOR_ATTEMPTS, type BoardGroup, type BoardNode } from "../../board/roster";
import { count, percent } from "../../lib/format";
import type { Segment } from "../../lib/types";

/**
 * Payment health, as deviation from each segment's own baseline.
 *
 * A grid of success rates answers "what is the rate here" and makes you read every cell to find
 * the one that matters. This answers "where is the concentration of failures" instead: every
 * segment sits on one shared 0 to 100 percent axis, the bar runs from the segment's own baseline
 * to where it actually is, so the bar's length is the excess and the eye finds the outlier by
 * running down the column.
 *
 * Three states, and the third is the point. A segment the detector could not test is drawn as a
 * dashed rule across an empty track rather than left out, because its absence from measurement is
 * a fact about the detector and not missing data. The roster in board/roster.ts is what makes
 * that possible, since the API omits a below-floor key entirely.
 *
 * Segment names are mono because they are keys a reader compares character by character. Rates
 * are in the display face, right aligned on tabular figures, so the column of numbers is itself
 * a shape.
 */

// The quarter ticks are dropped on a narrow column, where they collide with the ends.
const AXIS_TICKS: { at: number; minor: boolean }[] = [
  { at: 0, minor: false },
  { at: 0.25, minor: true },
  { at: 0.5, minor: false },
  { at: 0.75, minor: true },
  { at: 1, minor: false },
];

function Lane({ node, methodLabel }: { node: BoardNode; methodLabel: string }) {
  if (node.state === "below_floor") {
    const peak = Math.round(node.roster.expected_attempts_peak_window);
    return (
      <div className="lane-row row-hover">
        <div className="mono truncate" style={{ fontSize: 12, color: "var(--text-3)" }}>
          {node.instrument}
        </div>
        <div
          className="lane-track"
          role="img"
          aria-label={`${node.instrument}, below the detection floor. About ${peak} attempts expected in a peak window against a floor of ${FLOOR_ATTEMPTS}.`}
        >
          <div className="lane-empty" />
        </div>
        <div className="text-right" style={{ fontSize: 11, color: "var(--text-3)" }}>
          below floor
        </div>
        <div className="mono text-right" style={{ fontSize: 11, color: "var(--text-3)" }}>
          n &lt; {FLOOR_ATTEMPTS}
        </div>
      </div>
    );
  }

  const s: Segment = node.segment;
  const baseline = 1 - s.baseline;
  const value = s.rate;
  const worse = value < baseline;
  const left = Math.min(value, baseline);
  const width = Math.abs(value - baseline);
  const inIncident = Boolean(s.incident_id);

  const lane = (
    <div className="lane-row row-hover">
      <div className="flex items-center gap-2 truncate">
        {inIncident && (
          <span
            aria-hidden="true"
            className="inline-block h-3 w-[2px] shrink-0"
            style={{ background: "var(--incident)" }}
          />
        )}
        <span
          className="mono truncate"
          style={{
            fontSize: 12,
            color: inIncident ? "var(--incident)" : "var(--text-2)",
            fontWeight: inIncident ? 500 : 400,
          }}
        >
          {node.instrument}
        </span>
      </div>

      <div
        className="lane-track"
        role="img"
        aria-label={`${methodLabel} ${node.instrument}, success rate ${percent(value)}, baseline ${percent(baseline)}, ${s.attempts} attempts${inIncident ? ", inside an open incident" : ""}`}
      >
        {/* Red is the excess failure. The other direction is a segment doing better than its own
            baseline, which is not an incident, so it is never drawn in the incident colour. */}
        <div
          className="lane-fill"
          style={{
            left: `${left * 100}%`,
            width: `${Math.max(width, 0.002) * 100}%`,
            background: worse ? "var(--incident)" : "var(--recovered)",
            opacity: worse ? 0.9 : 0.5,
          }}
        />
        <div className="lane-baseline" style={{ left: `${baseline * 100}%` }} />
        <div className="lane-value" style={{ left: `calc(${value * 100}% - 1px)` }} />
      </div>

      <div
        className="display text-right"
        style={{ fontSize: 14, color: worse ? "var(--incident)" : "var(--text)" }}
      >
        {percent(value)}
      </div>
      <div className="mono text-right" style={{ fontSize: 11, color: "var(--text-3)" }}>
        n {count(s.attempts)}
      </div>
    </div>
  );

  return inIncident ? (
    <Link to={`/incidents/${s.incident_id}`} className="focus-ring block">
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
    <div className="lane-row" style={{ gridTemplateColumns: "10rem minmax(0, 1fr)" }}>
      <div className="mono truncate" style={{ fontSize: 12, color: "var(--text-3)" }}>
        {group.title}
      </div>
      <div style={{ fontSize: 11, color: "var(--text-3)" }}>
        <span style={{ color: "var(--text-2)" }}>{collapsed.label}</span>
        {collapsed.nodeCount > 0 && <span> &middot; {collapsed.nodeCount} keys</span>}
      </div>
    </div>
  );
}

export function SegmentMatrix({ segments }: { segments: Segment[] }) {
  const board = buildBoard(segments);

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-x-10 gap-y-4">
        <h2 className="display heading">Payment health</h2>
        <p className="body-sm max-w-md">
          Bars run from each segment&rsquo;s own baseline to where it is now, on one shared axis.
          Length is the excess, direction is the sign. <span className="mono">{board.measured}</span>{" "}
          of <span className="mono">{board.total}</span> segments cleared the {FLOOR_ATTEMPTS}
          -attempt floor in this window; the rest are drawn as an empty track, because a segment
          the detector cannot test is a fact about the detector, not missing data.
        </p>
      </div>

      {/* The axis is declared once, at the top, and every lane below shares it. */}
      <div
        className="lane-row mt-6"
        style={{ borderTop: "1px solid var(--hair-strong)", paddingTop: 8 }}
      >
        <div className="microlabel">segment</div>
        <div className="relative h-3">
          {AXIS_TICKS.map((tick) => (
            <span
              key={tick.at}
              className={`microlabel absolute -top-0.5 ${tick.minor ? "hidden xl:inline" : ""}`}
              style={{
                left: `${tick.at * 100}%`,
                transform: tick.at === 1 ? "translateX(-100%)" : undefined,
              }}
            >
              {tick.at * 100}
            </span>
          ))}
        </div>
        <div className="microlabel text-right">success</div>
        <div className="microlabel text-right">volume</div>
      </div>

      <div className="mt-2">
        {board.methods.map((entry) => {
          const method = entry.methodNode;
          const measured = method && method.state === "measured" ? method.segment : null;
          return (
            <section
              key={entry.method}
              className="mt-5 pt-4"
              style={{ borderTop: "1px solid var(--hair)" }}
            >
              <header className="flex items-baseline gap-4">
                <h3
                  className="display"
                  style={{ fontSize: 16, textTransform: "uppercase", letterSpacing: "0.04em" }}
                >
                  {entry.method}
                </h3>
                {measured ? (
                  <>
                    <span className="display" style={{ fontSize: 14, color: "var(--text-2)" }}>
                      {percent(measured.rate)}
                    </span>
                    <span className="microlabel">{count(measured.attempts)} attempts</span>
                  </>
                ) : (
                  <span className="microlabel">below detection floor</span>
                )}
              </header>
              {entry.groups.map((group) =>
                group.collapsed ? (
                  <Collapsed key={group.id} group={group} />
                ) : (
                  <div key={group.id} className="mt-3">
                    <div className="microlabel pb-1">{group.title}</div>
                    {group.nodes.map((node) => (
                      <Lane key={node.key} node={node} methodLabel={entry.method} />
                    ))}
                  </div>
                ),
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}
