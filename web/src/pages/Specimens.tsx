/**
 * The specimen sheet. Every primitive at every state, on synthetic data.
 *
 * Not a page of the console and not in the navigation. It exists to be looked at: each specimen
 * is labelled with the state it is in, so a state can be judged on its own rather than waiting
 * for a world to produce it. Nothing here fetches, and nothing here is real. The numbers are
 * chosen to sit on the boundaries that matter, which is why several of them look implausible.
 *
 * `Cell` and `CollapsedGroup` are imported from pages/Overview.tsx rather than copied, so the
 * specimen and the board cannot drift. Overview is not restyled: the visual system lives in
 * specimens.css, scoped under `.specimen-sheet`, and is applied to the real tile as a skin.
 */
import { useEffect, useState, type ReactNode } from "react";
import {
  Badge,
  Code,
  ConfirmButton,
  Disclosure,
  Empty,
  ErrorPanel,
  Loading,
  Panel,
  Region,
  Stat,
  StatusBadge,
  Table,
} from "../components/primitives";
import { Cell, CollapsedGroup } from "./Overview";
import { FLOOR_ATTEMPTS, type BoardGroup, type BoardNode, type RosterNode } from "../board/roster";
import type { Segment } from "../lib/types";
import "./specimens.css";

// The display face. Injected on mount rather than linked from index.html, so one route's
// typography does not put a font request on every page of the console. Reason logged here rather
// than in the dependency list because it adds no package: it is a stylesheet link, and the CSS
// carries a full fallback stack for when it does not arrive.
const FONT_HREF =
  "https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&display=swap";

function useDisplayFace() {
  useEffect(() => {
    if (document.head.querySelector(`link[href="${FONT_HREF}"]`)) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = FONT_HREF;
    document.head.appendChild(link);
  }, []);
}

// -- sheet furniture -------------------------------------------------------

function Section({ title, note, children }: { title: string; note?: ReactNode; children: ReactNode }) {
  return (
    <section className="mt-8">
      <h2 className="display text-[13px] uppercase tracking-[0.08em]">{title}</h2>
      {note && <p className="caption mt-1 max-w-3xl">{note}</p>}
      <div className="mt-3 flex flex-wrap items-start gap-5">{children}</div>
    </section>
  );
}

function Specimen({
  state,
  note,
  width,
  children,
}: {
  state: string;
  note?: string;
  width?: string;
  children: ReactNode;
}) {
  return (
    <figure className="m-0" style={width ? { width } : undefined}>
      <div>{children}</div>
      <figcaption className="mt-1.5 max-w-[15rem]">
        <div className="num text-[11px] font-medium" style={{ color: "var(--ink-soft)" }}>
          {state}
        </div>
        {note && <div className="caption-faint">{note}</div>}
      </figcaption>
    </figure>
  );
}

// -- synthetic data --------------------------------------------------------

function segment(
  instrument: string,
  failure_rate: number,
  baseline: number,
  attempts = 48,
  incident_id: string | null = null,
): Segment {
  return {
    key: `upi:upi_handle:${instrument}`,
    method: "upi",
    instrument,
    attempts,
    failures: Math.round(attempts * failure_rate),
    rate: 1 - failure_rate,
    failure_rate,
    baseline,
    incident_id,
  };
}

function roster(instrument: string, peak: number, marginal: boolean): RosterNode {
  return {
    key: `card:card_bin6:${instrument}`,
    method: "card",
    instrument,
    group: "card_bin6",
    share_of_all_attempts: 0.02,
    expected_attempts_mean_window: peak / 2.5,
    expected_attempts_peak_window: peak,
    reaches_floor_at_peak: peak >= FLOOR_ATTEMPTS,
    marginal_at_peak: marginal,
  };
}

const measured = (s: Segment): BoardNode => ({
  state: "measured",
  key: s.key,
  instrument: s.instrument,
  segment: s,
  roster: null,
});

const belowFloor = (node: RosterNode): BoardNode => ({
  state: "below_floor",
  key: node.key,
  instrument: node.instrument,
  roster: node,
});

const collapsed = (
  id: string,
  title: string,
  label: string,
  detail: string,
  nodeCount: number,
): BoardGroup => ({ id, title, nodes: [], collapsed: { label, detail, nodeCount } });

// One per step of the scale in Overview's cellColour, each just inside its boundary.
const SCALE: { state: string; note: string; node: BoardNode }[] = [
  { state: "excess >= 0.30", note: "top step", node: measured(segment("okhdfcbank", 0.42, 0.1)) },
  { state: "excess >= 0.15", note: "", node: measured(segment("oksbi", 0.27, 0.1)) },
  { state: "excess >= 0.07", note: "", node: measured(segment("okicici", 0.18, 0.1)) },
  { state: "excess >= 0.03", note: "amber step", node: measured(segment("ybl", 0.14, 0.1)) },
  { state: "excess < 0.03", note: "inside baseline", node: measured(segment("paytm", 0.11, 0.1)) },
];

const TABLE_ROWS = [
  { opened: "20:03", segment: "upi / okhdfcbank", cause: "issuer outage", risk: "25,631.93" },
  { opened: "19:48", segment: "card / 411111", cause: "auth failure bin", risk: "8,204.10" },
  { opened: "18:15", segment: "all", cause: "gateway degradation", risk: "1,02,455.00" },
];

// -- the sheet -------------------------------------------------------------

export default function SpecimensPage() {
  useDisplayFace();
  const [retried, setRetried] = useState(0);
  const noop = () => setRetried((n) => n + 1);

  return (
    <div className="specimen-sheet">
      <header>
        <h1 className="text-[22px]">Specimen sheet</h1>
        <p className="caption mt-1.5 max-w-3xl text-[12px]">
          Every primitive at every state, on synthetic data. Nothing here is measured and nothing
          here fetches. Numbers sit on the boundaries of the scales they belong to, so several are
          deliberately implausible as traffic. The board tile and the collapsed group row are the
          real components imported from Overview, wearing this sheet&rsquo;s skin; Overview itself
          is unchanged.
        </p>
      </header>

      <Section
        title="Depth, three levels on identical shapes"
        note="Every raised element is a border darker than its surface, an inset top highlight, and a cast shadow. Take one away and the object flattens, which is what the fourth specimen is for."
      >
        <Specimen state="level 1, flat" note="information. Tone difference only, no shadow.">
          <div className="lvl lvl-1">
            <div className="display text-[12px]">nb_bank</div>
            <div className="caption-faint mt-1">below detection floor</div>
          </div>
        </Specimen>
        <Specimen state="level 2, default" note="border, inset highlight, 0 2px 3px at 12 percent.">
          <div className="lvl lvl-2">
            <div className="display text-[12px]">okicici</div>
            <div className="num mt-0.5 text-[15px] font-semibold">83.3%</div>
            <div className="num caption-faint">n 30</div>
          </div>
        </Specimen>
        <Specimen state="level 3, active" note="0 4px 8px at 16 percent, lifted 1px, stronger highlight.">
          <div className="lvl lvl-3">
            <div className="display text-[12px]">okhdfcbank</div>
            <div className="num mt-0.5 text-[15px] font-semibold">5.6%</div>
            <div className="num caption-faint">n 54</div>
          </div>
        </Specimen>
        <Specimen state="level 0, banned" note="border only. Here so the miss is visible, and nowhere else.">
          <div className="lvl lvl-0" style={{ opacity: 0.85 }}>
            <div className="text-[12px] font-medium">okhdfcbank</div>
            <div className="num mt-0.5 text-[15px] font-semibold">5.6%</div>
            <div className="num caption-faint">n 54</div>
          </div>
        </Specimen>
      </Section>

      <Section
        title="Surface tones"
        note="A tile can only sit on something if that something is a different colour. Page, board and group region are three steps of one warm ivory, and the region is recessed into the board rather than drawn on it."
      >
        <Specimen state="page" note="#F2EDE4">
          <div className="swatch" style={{ background: "var(--page)" }} />
        </Specimen>
        <Specimen state="board" note="raised off the page">
          <div className="swatch" style={{ background: "var(--board)", boxShadow: "var(--highlight), var(--cast-2)" }} />
        </Specimen>
        <Specimen state="group region" note="recessed into the board">
          <div className="swatch" style={{ background: "var(--region)", boxShadow: "var(--recess)" }} />
        </Specimen>
        <Specimen state="tile face" note="raised off the region">
          <div className="swatch" style={{ background: "var(--face)", boxShadow: "var(--highlight), var(--cast-2)" }} />
        </Specimen>
        <Specimen state="all four, assembled" width="100%" note="the same three tones doing their job">
          <div className="board">
            <div className="display mb-2 text-[12px]">upi</div>
            <div className="region flex flex-wrap gap-2">
              {SCALE.slice(0, 3).map((entry) => (
                <div key={entry.state} className="tile-host">
                  <Cell node={entry.node} />
                </div>
              ))}
              <div className="tile-host is-below">
                <Cell node={belowFloor(roster("601136", 7.9, false))} />
              </div>
            </div>
          </div>
        </Specimen>
      </Section>

      <Section
        title="Board tile, the real component"
        note="Imported from Overview. The five steps of the excess scale, remapped into the ivory world's reds so the board is one material rather than two."
      >
        {SCALE.map((entry) => (
          <Specimen key={entry.state} state={entry.state} note={entry.note}>
            <div className="tile-host">
              <Cell node={entry.node} />
            </div>
          </Specimen>
        ))}
      </Section>

      <Section title="Board tile, other states">
        <Specimen state="inside an open incident" note="state colour on the edge, and it is level 3">
          <div className="tile-host is-selected">
            <Cell node={measured(segment("okhdfcbank", 0.944, 0.1, 54, "inc_1"))} />
          </div>
        </Specimen>
        <Specimen state="measured, zero attempts" note="tested window, no traffic in it">
          <div className="tile-host">
            <Cell node={measured(segment("508500", 0, 0.16, 0))} />
          </div>
        </Specimen>
        <Specimen
          state="below detection floor"
          note={`in the roster, absent from the response. Fewer than ${FLOOR_ATTEMPTS} attempts, so it is recessed, not raised.`}
        >
          <div className="tile-host is-below">
            <Cell node={belowFloor(roster("601136", 7.9, false))} />
          </div>
        </Specimen>
        <Specimen state="below floor, marginal" note="same face, different tooltip. Flips window to window.">
          <div className="tile-host is-below">
            <Cell node={belowFloor(roster("MasterCard", 19.7, true))} />
          </div>
        </Specimen>
        <Specimen state="long instrument name" note="truncation, not wrapping">
          <div className="tile-host">
            <Cell node={measured(segment("a-very-long-handle-name", 0.12, 0.1))} />
          </div>
        </Specimen>
      </Section>

      <Section
        title="Board group, collapsed"
        note="Two different claims. One is about measurement, the other about the detector's dimensions, and they should not read alike."
      >
        <Specimen state="below floor at all hours" note="netbanking banks" width="100%">
          <div className="collapsed-host">
            <CollapsedGroup
              group={collapsed(
                "nb_bank",
                "bank",
                "below detection floor at all hours",
                "All 5 exist as segment keys. The busiest sees about 9 attempts in a peak 15-minute window against a floor of 20.",
                5,
              )}
            />
          </div>
        </Specimen>
        <Specimen state="no instrument dimension" note="wallet" width="100%">
          <div className="collapsed-host">
            <CollapsedGroup
              group={collapsed(
                "wallet_none",
                "instrument",
                "no instrument dimension",
                "wallet is not one of the detector's INSTRUMENT_DIMENSIONS, so wallet attempts only ever produce the `all` and `wallet` keys.",
                0,
              )}
            />
          </div>
        </Specimen>
      </Section>

      <Section
        title="Tokens"
        note="Objects, not dots. Radial highlight offset toward the top left so the light agrees with every raised surface around it, and a tight contact shadow directly beneath so they sit on the surface rather than float over it."
      >
        {(["10", "12", "14"] as const).map((size) => (
          <Specimen key={size} state={`${size}px, neutral`}>
            <span className={`token token-${size} token-neutral`} />
          </Specimen>
        ))}
        <Specimen state="incident" note="active incident, refused action">
          <span className="token token-12 token-incident" />
        </Specimen>
        <Specimen state="pending" note="escalation awaiting a human, deferred action">
          <span className="token token-12 token-pending" />
        </Specimen>
        <Specimen state="recovered">
          <span className="token token-12 token-recovered" />
        </Specimen>
        <Specimen state="in a tile" width="100%" note="the status indicator sitting on the tile face">
          <div className="lvl lvl-2" style={{ width: "180px" }}>
            <div className="flex items-center justify-between">
              <span className="display text-[12px]">okhdfcbank</span>
              <span className="token token-10 token-incident" />
            </div>
            <div className="num mt-0.5 text-[15px] font-semibold">5.6%</div>
            <div className="num caption-faint">base 89.7% / n 54</div>
          </div>
        </Specimen>
      </Section>

      <Section
        title="Chrome"
        note="Milled into the board, not painted a different colour. The rail is the same ivory recessed a step, with the active item raised back out of it. No navy against cream."
      >
        <Specimen state="top bar" width="100%">
          <div className="chrome flex items-center justify-between px-3 py-1.5">
            <span className="display text-[13px]">Salvage</span>
            <span className="num caption">sim 20:45 &middot; dev</span>
          </div>
        </Specimen>
        <Specimen state="nav rail" width="12rem">
          <div className="chrome py-1.5">
            {["Overview", "Incidents", "Escalations", "Ledger"].map((item, index) => (
              <div key={item} className={`chrome-item ${index === 1 ? "is-active" : ""}`}>
                {item}
              </div>
            ))}
          </div>
        </Specimen>
      </Section>

      <Section
        title="Shape"
        note="Radius varies on purpose. Physical blocks 3px, information panels 1px. Not everything the same."
      >
        <Specimen state="physical block, 3px">
          <div className="lvl lvl-2" style={{ borderRadius: "3px" }} />
        </Specimen>
        <Specimen state="information panel, 1px">
          <div className="lvl lvl-1" style={{ borderRadius: "1px" }} />
        </Specimen>
      </Section>

      <Section
        title="Typography"
        note="Display face for headings and node names. UI sans for prose. Monospace strictly for numbers, ids, hashes and timestamps, which is what the `.num` class already marks."
      >
        <Specimen state="display" width="16rem">
          <div className="display text-[18px]">okhdfcbank</div>
        </Specimen>
        <Specimen state="UI sans" width="16rem">
          <div className="text-[13px]">Two consecutive windows above threshold.</div>
        </Specimen>
        <Specimen state="mono, numbers" width="16rem">
          <div className="num text-[13px]">25,631.93 &middot; 20:45:00 &middot; inc_upi_okhdfcbank</div>
        </Specimen>
      </Section>

      <Section title="Stat">
        <Specimen state="neutral, with hint">
          <Stat label="Attempts, last hour" value="1,227" hint="window ends 20:45 sim" />
        </Specimen>
        <Specimen state="neutral, no hint">
          <Stat label="Attempts, last hour" value="1,227" />
        </Specimen>
        <Specimen state="red">
          <Stat label="Success rate, last hour" value="78.2%" tone="red" />
        </Specimen>
        <Specimen state="amber">
          <Stat label="At-risk revenue" value="25,631.93" hint="open incidents" tone="amber" />
        </Specimen>
        <Specimen state="green">
          <Stat
            label="Recovered, all time"
            value="0.00"
            hint="link and steer routes only, excludes organic recovery"
            tone="green"
          />
        </Specimen>
        <Specimen state="accent">
          <Stat label="Cases" value="112" tone="accent" />
        </Specimen>
        <Specimen state="null value" note="success rate with no attempts in the hour">
          <Stat label="Success rate, last hour" value="-" />
        </Specimen>
        <Specimen state="long value" note="does it hold its box">
          <Stat label="At-risk revenue" value="1,02,45,631.93" hint="open incidents" />
        </Specimen>
      </Section>

      <Section title="Badge">
        {(["neutral", "red", "amber", "green", "accent"] as const).map((tone) => (
          <Specimen key={tone} state={tone}>
            <Badge tone={tone}>{tone}</Badge>
          </Specimen>
        ))}
      </Section>

      <Section title="StatusBadge" note="Colour is never the only signal, so every state carries its own word.">
        {["open", "recovering", "escalated", "paused", "closed", "unknown"].map((status) => (
          <Specimen key={status} state={status}>
            <StatusBadge status={status} />
          </Specimen>
        ))}
      </Section>

      <Section title="Panel">
        <Specimen state="title only" width="20rem">
          <Panel title="Active incidents">
            <p className="text-sm">Body.</p>
          </Panel>
        </Specimen>
        <Specimen state="title and subtitle" width="24rem">
          <Panel
            title="Success rate by segment"
            subtitle="Current 15-minute window. 19 of 33 segments cleared the 20-attempt floor."
          >
            <p className="text-sm">Body.</p>
          </Panel>
        </Specimen>
        <Specimen state="title and right slot" width="22rem">
          <Panel title="Incident" right={<StatusBadge status="escalated" />}>
            <p className="text-sm">Body.</p>
          </Panel>
        </Specimen>
        <Specimen state="no header" width="16rem">
          <Panel>
            <p className="text-sm">Body with no header.</p>
          </Panel>
        </Specimen>
      </Section>

      <Section title="Table">
        <Specimen state="rows, mixed alignment" width="100%">
          <Table
            columns={["opened", "segment", "root cause", "at risk"]}
            align={["left", "left", "left", "right"]}
          >
            {TABLE_ROWS.map((row) => (
              <tr key={row.opened} className="border-b border-neutral-200">
                <td className="cell-pad num">{row.opened}</td>
                <td className="cell-pad num">{row.segment}</td>
                <td className="cell-pad">{row.cause}</td>
                <td className="cell-pad num text-right">{row.risk}</td>
              </tr>
            ))}
          </Table>
        </Specimen>
        <Specimen state="no rows" width="100%" note="the header still has to hold">
          <Table columns={["opened", "segment", "root cause", "at risk"]}>{null}</Table>
        </Specimen>
      </Section>

      <Section title="Loading, Empty, ErrorPanel">
        <Specimen state="Loading, 3 rows" width="18rem">
          <Loading rows={3} />
        </Specimen>
        <Specimen state="Empty" width="18rem">
          <Empty>Nothing open. Every segment is inside its baseline.</Empty>
        </Specimen>
        <Specimen state="Empty with action" width="18rem">
          <Empty action={<span className="text-sm text-accent">Go to Scenario Runner</span>}>
            No attempts yet. Run a scenario.
          </Empty>
        </Specimen>
        <Specimen state="ErrorPanel with retry" width="22rem">
          <ErrorPanel error={new Error("connection refused")} retry={noop} />
        </Specimen>
        <Specimen state="ErrorPanel, no retry" width="22rem">
          <ErrorPanel error={new Error("connection refused")} />
        </Specimen>
      </Section>

      <Section
        title="Region"
        note="The three mandatory data-region states in one wrapper, so a page cannot forget one."
      >
        <Specimen state="loading" width="18rem">
          <Region state={{ data: null, error: null, loading: true, reload: noop }} rows={2}>
            {() => null}
          </Region>
        </Specimen>
        <Specimen state="error" width="22rem">
          <Region
            state={{
              data: null,
              error: new Error("502 from /api/overview"),
              loading: false,
              reload: noop,
            }}
          >
            {() => null}
          </Region>
        </Specimen>
        <Specimen state="empty" width="18rem">
          <Region
            state={{ data: null, error: null, loading: false, reload: noop }}
            empty={<span>No attempts yet.</span>}
          >
            {() => null}
          </Region>
        </Specimen>
        <Specimen state="data" width="18rem" note={`reload fired ${retried} time(s)`}>
          <Region state={{ data: "loaded", error: null, loading: false, reload: noop }}>
            {(data) => <p className="text-sm">{data}</p>}
          </Region>
        </Specimen>
      </Section>

      <Section title="Disclosure and Code">
        <Specimen state="Disclosure, closed" width="20rem" note="click to open">
          <Disclosure summary="Show prompt and raw response">
            <Code>{'{\n  "cause": "issuer_outage"\n}'}</Code>
          </Disclosure>
        </Specimen>
        <Specimen state="Code, short" width="20rem">
          <Code>upi:upi_handle:okhdfcbank</Code>
        </Specimen>
        <Specimen state="Code, long" width="24rem" note="scrolls inside its own box">
          <Code>
            {Array.from({ length: 24 }, (_, i) => `line ${i + 1}: a fairly long line of output`).join(
              "\n",
            )}
          </Code>
        </Specimen>
      </Section>

      <Section
        title="ConfirmButton"
        note="Stateful. The idle and locked states are shown; clicking a live one opens its confirm panel in place."
      >
        <Specimen state="accent, enabled">
          <ConfirmButton label="Close incident" prompt="Close this incident?" onConfirm={async () => {}} />
        </Specimen>
        <Specimen state="red, enabled">
          <ConfirmButton
            label="Kill switch"
            tone="red"
            prompt="Suspend all outbound actions?"
            onConfirm={async () => {}}
          />
        </Specimen>
        <Specimen state="green, requires a note">
          <ConfirmButton
            label="Approve"
            tone="green"
            requireNote
            notePlaceholder="Reason"
            prompt="Approve this escalation?"
            onConfirm={async () => {}}
          />
        </Specimen>
        <Specimen state="disabled, with reason" note="lock glyph, reason beside it">
          <ConfirmButton
            label="Approve"
            disabled
            disabledReason="needs the dashboard token"
            prompt="Approve this escalation?"
            onConfirm={async () => {}}
          />
        </Specimen>
        <Specimen state="failure inside the panel" note="open it and confirm; the note is kept">
          <ConfirmButton
            label="Reject"
            tone="red"
            requireNote
            prompt="Reject this escalation?"
            onConfirm={async () => {
              throw new Error("403 from /api/escalations/esc_1/decision");
            }}
          />
        </Specimen>
      </Section>
    </div>
  );
}
