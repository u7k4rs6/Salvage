/**
 * The specimen sheet. Every primitive at every state, on synthetic data.
 *
 * Not a page of the console and not in the navigation. It exists to be looked at: each specimen
 * is labelled with the state it is in, so a state can be judged on its own rather than waiting
 * for a world to produce it. Nothing here fetches, and nothing here is real. The numbers are
 * chosen to sit on the boundaries that matter, which is why several of them look implausible.
 *
 * The board tile markup below is duplicated from `pages/Overview.tsx` rather than imported,
 * because Overview does not export it and this sheet was built under an instruction not to touch
 * that file. That is a drift risk and it is the reason to import it instead as soon as the two
 * are allowed to move together.
 */
import { useState, type ReactNode } from "react";
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
import { FLOOR_ATTEMPTS } from "../board/roster";

// -- sheet furniture -------------------------------------------------------

function Section({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section className="border-t border-neutral-300 pt-4">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-900">{title}</h2>
      {note && <p className="mt-0.5 max-w-3xl text-xs text-neutral-600">{note}</p>}
      <div className="mt-3 flex flex-wrap items-start gap-4">{children}</div>
    </section>
  );
}

/** One specimen, under the name of the state it is in. */
function Specimen({
  state,
  note,
  width = "auto",
  children,
}: {
  state: string;
  note?: string;
  width?: string;
  children: ReactNode;
}) {
  return (
    <figure className="m-0" style={{ width }}>
      <div>{children}</div>
      <figcaption className="mt-1 max-w-xs">
        <div className="num text-[11px] font-medium text-neutral-700">{state}</div>
        {note && <div className="text-[10px] leading-tight text-neutral-500">{note}</div>}
      </figcaption>
    </figure>
  );
}

// -- synthetic data --------------------------------------------------------

type SpecimenSegment = {
  instrument: string;
  rate: number;
  failure_rate: number;
  baseline: number;
  attempts: number;
  incident: boolean;
};

function segment(
  instrument: string,
  failure_rate: number,
  baseline: number,
  attempts = 48,
  incident = false,
): SpecimenSegment {
  return { instrument, rate: 1 - failure_rate, failure_rate, baseline, attempts, incident };
}

// One per step of the colour scale in Overview's cellColour, chosen to land just inside each
// boundary rather than in the middle of a band.
const SCALE: { state: string; note: string; segment: SpecimenSegment }[] = [
  {
    state: "excess >= 0.30",
    note: "the top step, solid red",
    segment: segment("okhdfcbank", 0.42, 0.1),
  },
  { state: "excess >= 0.15", note: "", segment: segment("oksbi", 0.27, 0.1) },
  { state: "excess >= 0.07", note: "", segment: segment("okicici", 0.18, 0.1) },
  { state: "excess >= 0.03", note: "the amber step", segment: segment("ybl", 0.14, 0.1) },
  { state: "excess < 0.03", note: "inside baseline", segment: segment("paytm", 0.11, 0.1) },
];

const TABLE_ROWS = [
  { opened: "20:03", segment: "upi / okhdfcbank", cause: "issuer outage", risk: "25,631.93" },
  { opened: "19:48", segment: "card / 411111", cause: "auth failure bin", risk: "8,204.10" },
  { opened: "18:15", segment: "all", cause: "gateway degradation", risk: "1,02,455.00" },
];

// -- the board tile, mirrored from Overview --------------------------------

function cellColour(s: SpecimenSegment): string {
  const excess = s.failure_rate - s.baseline;
  if (s.attempts === 0) return "bg-neutral-50 text-neutral-400";
  if (excess >= 0.3) return "bg-red-600 text-white";
  if (excess >= 0.15) return "bg-red-400 text-white";
  if (excess >= 0.07) return "bg-red-200 text-red-900";
  if (excess >= 0.03) return "bg-amber-100 text-amber-900";
  return "bg-neutral-100 text-neutral-700";
}

function MeasuredTile({ s }: { s: SpecimenSegment }) {
  return (
    <div
      className={`h-full w-36 border ${
        s.incident ? "border-2 border-red-600" : "border-neutral-200"
      } ${cellColour(s)} px-2 py-1.5`}
    >
      <div className="truncate text-[11px] font-medium">{s.instrument}</div>
      <div className="num text-sm font-semibold">{(s.rate * 100).toFixed(1)}%</div>
      <div className="num text-[10px] opacity-80">
        base {((1 - s.baseline) * 100).toFixed(1)}% / n {s.attempts}
      </div>
      {s.incident && <div className="mt-0.5 text-[10px] font-semibold">incident</div>}
    </div>
  );
}

function BelowFloorTile({ instrument }: { instrument: string }) {
  return (
    <div className="h-full w-36 border border-dashed border-neutral-300 bg-neutral-50 px-2 py-1.5 text-neutral-400">
      <div className="truncate text-[11px] font-medium">{instrument}</div>
      <div className="text-[10px] leading-tight">below detection floor</div>
    </div>
  );
}

function CollapsedRow({ title, label, detail }: { title: string; label: string; detail: string }) {
  return (
    <div className="flex w-full max-w-2xl flex-wrap items-baseline gap-x-2 gap-y-1 border border-dashed border-neutral-300 bg-neutral-50 px-2 py-1.5">
      <span className="text-[11px] font-medium text-neutral-500">{title}</span>
      <span className="text-[11px] text-neutral-500">{label}</span>
      <span className="text-[10px] text-neutral-400">{detail}</span>
    </div>
  );
}

// -- the sheet -------------------------------------------------------------

export default function SpecimensPage() {
  // Region takes a live-looking state object. These are the four it must handle.
  const [retried, setRetried] = useState(0);
  const noop = () => setRetried((n) => n + 1);

  return (
    <div className="space-y-6 pb-16">
      <header>
        <h1 className="text-lg font-semibold text-neutral-900">Specimen sheet</h1>
        <p className="mt-1 max-w-3xl text-sm text-neutral-700">
          Every primitive at every state, on synthetic data. Nothing here is measured and nothing
          here fetches. Numbers sit on the boundaries of the scales they belong to, so several of
          them are deliberately implausible as traffic.
        </p>
        <p className="mt-1 max-w-3xl text-xs text-neutral-600">
          The visual brief for depth, colour direction, token shape and typeface has not been
          applied: it was not in the thread this file was built from. What is below uses the
          tokens the console ships with today.
        </p>
      </header>

      <Section
        title="Board tile, measured"
        note="Five steps on the excess failure rate, not a gradient. Each specimen sits just inside its boundary."
      >
        {SCALE.map((entry) => (
          <Specimen key={entry.state} state={entry.state} note={entry.note}>
            <MeasuredTile s={entry.segment} />
          </Specimen>
        ))}
      </Section>

      <Section title="Board tile, other states">
        <Specimen state="inside an open incident" note="red outline, links to the incident">
          <MeasuredTile s={segment("okhdfcbank", 0.94, 0.1, 54, true)} />
        </Specimen>
        <Specimen state="measured, zero attempts" note="tested window, no traffic in it">
          <MeasuredTile s={segment("508500", 0, 0.16, 0)} />
        </Specimen>
        <Specimen
          state="below detection floor"
          note={`in the roster, absent from the response. Fewer than ${FLOOR_ATTEMPTS} attempts.`}
        >
          <BelowFloorTile instrument="601136" />
        </Specimen>
        <Specimen
          state="below floor, marginal"
          note="identical face, different tooltip. Sits close enough to the floor to flip window to window."
        >
          <BelowFloorTile instrument="MasterCard" />
        </Specimen>
        <Specimen state="long instrument name" note="truncation, not wrapping">
          <MeasuredTile s={segment("a-very-long-handle-name", 0.12, 0.1)} />
        </Specimen>
      </Section>

      <Section
        title="Board group, collapsed"
        note="Two different claims. One is about measurement, the other is about the detector's dimensions."
      >
        <Specimen state="below floor at all hours" note="netbanking banks">
          <CollapsedRow
            title="bank"
            label="below detection floor at all hours"
            detail="All 5 exist as segment keys. The busiest sees about 9 attempts in a peak 15-minute window against a floor of 20."
          />
        </Specimen>
        <Specimen state="no instrument dimension" note="wallet">
          <CollapsedRow
            title="instrument"
            label="no instrument dimension"
            detail="wallet is not one of the detector's INSTRUMENT_DIMENSIONS, so wallet attempts only ever produce the `all` and `wallet` keys."
          />
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
        <Specimen state="neutral">
          <Badge>neutral</Badge>
        </Specimen>
        <Specimen state="red">
          <Badge tone="red">red</Badge>
        </Specimen>
        <Specimen state="amber">
          <Badge tone="amber">escalated</Badge>
        </Specimen>
        <Specimen state="green">
          <Badge tone="green">recovered</Badge>
        </Specimen>
        <Specimen state="accent">
          <Badge tone="accent">accent</Badge>
        </Specimen>
      </Section>

      <Section
        title="StatusBadge"
        note="Colour is never the only signal, so every state carries its own word."
      >
        {["open", "recovering", "escalated", "paused", "closed", "unknown"].map((status) => (
          <Specimen key={status} state={status}>
            <StatusBadge status={status} />
          </Specimen>
        ))}
      </Section>

      <Section title="Panel">
        <Specimen state="title only" width="20rem">
          <Panel title="Active incidents">
            <p className="text-sm text-neutral-700">Body.</p>
          </Panel>
        </Specimen>
        <Specimen state="title and subtitle" width="24rem">
          <Panel
            title="Success rate by segment"
            subtitle="Current 15-minute window. 19 of 33 segments cleared the 20-attempt floor."
          >
            <p className="text-sm text-neutral-700">Body.</p>
          </Panel>
        </Specimen>
        <Specimen state="title and right slot" width="22rem">
          <Panel title="Incident" right={<StatusBadge status="escalated" />}>
            <p className="text-sm text-neutral-700">Body.</p>
          </Panel>
        </Specimen>
        <Specimen state="no header" width="16rem">
          <Panel>
            <p className="text-sm text-neutral-700">Body with no header.</p>
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
            state={{ data: null, error: new Error("502 from /api/overview"), loading: false, reload: noop }}
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
            {(data) => <p className="text-sm text-neutral-700">{data}</p>}
          </Region>
        </Specimen>
      </Section>

      <Section title="Disclosure and Code">
        <Specimen state="Disclosure, closed" width="20rem" note="click to open">
          <Disclosure summary="Show prompt and raw response">
            <Code>{"{\n  \"cause\": \"issuer_outage\"\n}"}</Code>
          </Disclosure>
        </Specimen>
        <Specimen state="Code, short" width="20rem">
          <Code>{"upi:upi_handle:okhdfcbank"}</Code>
        </Specimen>
        <Specimen state="Code, long" width="24rem" note="scrolls inside its own box">
          <Code>
            {Array.from({ length: 24 }, (_, i) => `line ${i + 1}: a fairly long line of output`).join("\n")}
          </Code>
        </Specimen>
      </Section>

      <Section
        title="ConfirmButton"
        note="Stateful. The idle and locked states are shown; clicking a live one opens its confirm panel in place."
      >
        <Specimen state="accent, enabled">
          <ConfirmButton
            label="Close incident"
            prompt="Close this incident?"
            onConfirm={async () => {}}
          />
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
