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
 * Three states, and the third is the point: a segment the detector could not test is drawn as a
 * hatched lane with no bar rather than left out, because its absence from measurement is a fact
 * about the detector and not missing data. The roster in board/roster.ts is what makes that
 * possible, since the API omits a below-floor key entirely.
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
    const peak = node.roster.expected_attempts_peak_window;
    return (
      <div className="row-hover grid grid-cols-[9.5rem_1fr_5.5rem_4rem] items-center gap-3 px-2 py-[3px]">
        <div className="truncate text-[12.5px] text-[color:var(--ink-3)]">{node.instrument}</div>
        <div
          className="lane-track lane-muted"
          role="img"
          aria-label={`${node.instrument}, below the detection floor. About ${peak} attempts expected in a peak window against a floor of ${FLOOR_ATTEMPTS}.`}
        />
        <div className="text-[11px] text-[color:var(--ink-3)]">below floor</div>
        <div className="num text-right text-[11px] text-[color:var(--ink-3)]">n &lt; {FLOOR_ATTEMPTS}</div>
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
    <div className="row-hover grid grid-cols-[9.5rem_1fr_5.5rem_4rem] items-center gap-3 px-2 py-[3px]">
      <div className="flex items-center gap-1.5 truncate">
        {inIncident && (
          <span
            aria-hidden="true"
            className="inline-block h-3 w-[3px] shrink-0"
            style={{ background: "var(--incident)" }}
          />
        )}
        <span
          className="truncate text-[12.5px]"
          style={{ color: inIncident ? "var(--incident)" : "var(--ink)", fontWeight: inIncident ? 600 : 450 }}
        >
          {node.instrument}
        </span>
      </div>
      <div
        className="lane-track"
        role="img"
        aria-label={`${methodLabel} ${node.instrument}, success rate ${percent(value)}, baseline ${percent(baseline)}, ${s.attempts} attempts${inIncident ? ", inside an open incident" : ""}`}
      >
        <div
          className="lane-fill"
          style={{
            left: `${left * 100}%`,
            width: `${Math.max(width, 0.002) * 100}%`,
            background: worse ? "var(--incident)" : "var(--recover)",
            opacity: worse ? 0.9 : 0.55,
          }}
        />
        <div className="lane-baseline" style={{ left: `${baseline * 100}%` }} />
        <div className="lane-value" style={{ left: `calc(${value * 100}% - 1px)` }} />
      </div>
      <div className="num text-[12.5px] tabular-nums" style={{ color: worse ? "var(--incident)" : "var(--ink)" }}>
        {percent(value)}
      </div>
      <div className="num text-right text-[11px] text-[color:var(--ink-3)]">n {count(s.attempts)}</div>
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
    <div className="grid grid-cols-[9.5rem_1fr] items-baseline gap-3 px-2 py-[5px]">
      <div className="truncate text-[12.5px] text-[color:var(--ink-3)]">{group.title}</div>
      <div className="text-[11px] text-[color:var(--ink-3)]">
        <span className="text-[color:var(--ink-2)]">{collapsed.label}</span>
        {collapsed.nodeCount > 0 && <span> &middot; {collapsed.nodeCount} keys</span>}
      </div>
    </div>
  );
}

export function SegmentMatrix({ segments }: { segments: Segment[] }) {
  const board = buildBoard(segments);

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="display text-[clamp(1.5rem,2.4vw,2.1rem)]">Payment health</h2>
        <p className="max-w-md text-[12px] leading-snug text-[color:var(--ink-2)]">
          Bars run from each segment&rsquo;s own baseline to where it is now, on one shared axis.
          Length is the excess, direction is the sign.{" "}
          <span className="num">{board.measured}</span> of{" "}
          <span className="num">{board.total}</span> segments cleared the{" "}
          {FLOOR_ATTEMPTS}-attempt floor in this window; the rest are drawn hatched, because a
          segment the detector cannot test is a fact about the detector, not missing data.
        </p>
      </div>

      {/* The axis is declared once, at the top, and every lane below shares it. */}
      <div className="rule-strong mt-4 grid grid-cols-[9.5rem_1fr_5.5rem_4rem] gap-3 px-2 pt-1.5">
        <div className="label">segment</div>
        <div className="relative h-3">
          {AXIS_TICKS.map((tick) => (
            <span
              key={tick.at}
              className={`label absolute -top-0.5 ${tick.minor ? "hidden xl:inline" : ""}`}
              style={{
                left: `${tick.at * 100}%`,
                transform: tick.at === 1 ? "translateX(-100%)" : undefined,
              }}
            >
              {tick.at * 100}
            </span>
          ))}
        </div>
        <div className="label">success</div>
        <div className="label text-right">volume</div>
      </div>

      <div className="mt-1">
        {board.methods.map((entry) => {
          const method = entry.methodNode;
          const measured = method && method.state === "measured" ? method.segment : null;
          return (
            <section key={entry.method} className="rule mt-3 pt-2.5">
              <header className="flex items-baseline gap-3 px-2">
                <h3 className="display text-[15px] uppercase tracking-[0.06em]">{entry.method}</h3>
                {measured ? (
                  <>
                    <span className="num text-[13px] tabular-nums">{percent(measured.rate)}</span>
                    <span className="label">{count(measured.attempts)} attempts</span>
                  </>
                ) : (
                  <span className="label">below detection floor</span>
                )}
              </header>
              {entry.groups.map((group) =>
                group.collapsed ? (
                  <Collapsed key={group.id} group={group} />
                ) : (
                  <div key={group.id} className="mt-1.5">
                    <div className="label px-2 pb-0.5">{group.title}</div>
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
