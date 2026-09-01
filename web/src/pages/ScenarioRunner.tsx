import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Section } from "../components/overview/Chrome";
import { ErrorPanel, Loading } from "../components/overview/States";
import { Transport } from "../components/replay/Transport";
import { Scrubber } from "../components/replay/Scrubber";
import { Health } from "../components/replay/Health";
import { Track } from "../components/replay/Track";
import { Diagnosis } from "../components/replay/Diagnosis";
import { Gates } from "../components/replay/Gates";
import { Cases } from "../components/replay/Cases";
import { Tail } from "../components/replay/Tail";
import { Entry } from "../components/replay/Entry";
import { Commentary } from "../components/replay/Commentary";
import { SCENARIOS, loadReplay, type ScenarioChoice } from "../replay/load";
import type { Replay } from "../replay/model";
import { stateAt, stageOf } from "../replay/state";
import { useReplay } from "../replay/useReplay";
import { narrate } from "../replay/narrate";
import { PROVES } from "../replay/verify";
import { count, rupeesShort, timeOnly, timestamp } from "../lib/format";
import { elapsed } from "../lib/health";
import "./overview.css";
import "./replay.css";
import { PageIntro } from "../components/PageIntro";

/**
 * The Scenario Runner: a recorded run, replayed from its own ledger.
 *
 * Why this page is a replay and not a live run. `POST /api/sim/run` simulates, detects, diagnoses,
 * acts and settles in one uninterruptible call. There is no moment during it at which the system
 * holds a partial world, so there is nothing to watch. The backend is not the problem to solve
 * here and it is not touched: the run is captured once, complete, and played back from the record
 * it left behind.
 *
 * The rule the whole page is built to keep: every frame is recorded data. The position of the head
 * is the only state, everything on screen is a pure function of it, and where a value was not
 * recorded the page shows nothing rather than a guess. There is no interpolation, no easing
 * between data points and no ambient motion anywhere.
 *
 * What the recording holds and what it does not:
 *
 *   The chain holds detection, diagnosis, evidence, the plan, every gate ladder, every action and
 *   its outcome, the link and steer recoveries, opt-outs, escalations and the close.
 *
 *   The chain does not hold per-window segment health, and it does not hold the two case terminals
 *   the scheduler reaches without writing an entry. Both come from read-only table dumps in the
 *   same recording, and both are labelled as such on the panels that use them.
 */

export default function ScenarioRunnerPage() {
  const [choice, setChoice] = useState<ScenarioChoice>(SCENARIOS[0]);
  const [replay, setReplay] = useState<Replay | null>(null);
  // Held above the Runner, which is remounted whenever the recording changes. The entry screen is
  // shown once per visit, not once per recording.
  const [started, setStarted] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let live = true;
    setReplay(null);
    setError(null);
    loadReplay(choice).then(
      (loaded) => {
        if (live) setReplay(loaded);
      },
      (failure) => {
        if (live) setError(failure);
      },
    );
    return () => {
      live = false;
    };
  }, [choice]);

  if (error) {
    return (
      <div className="ov rp">
        <Section title="Scenario Runner">
          <ErrorPanel error={error} retry={() => setChoice({ ...choice })} />
          <p className="note mt-3">
            The recordings live in <span className="mono">web/src/board/fixtures/</span>. The
            command that produces one is in <span className="mono">docs/BUILD_LOG.md</span>.
          </p>
        </Section>
      </div>
    );
  }

  if (!replay) {
    return (
      <div className="ov rp">
        <Section title="Scenario Runner">
          <Loading rows={5} label="Loading the recording" />
        </Section>
      </div>
    );
  }

  return <Runner key={choice.id} replay={replay} choice={choice} onChoose={setChoice} started={started} onStarted={setStarted} />;
}

/** The dissolve. One transition, matched by the `is-leaving` rule in replay.css. */
const CURTAIN_FADE_MS = 400;
/**
 * The preview loop behind the scrim.
 *
 * The first ninety seconds of the recording, walked in real time over twelve seconds and then
 * started again. It is the real recording rather than an animation, so the deviation bars behind
 * the headline are the segment actually degrading; the visitor is watching the thing go wrong
 * before they have decided to press anything.
 */
const PREVIEW_SIM_SECONDS = 90;
const PREVIEW_REAL_MS = 12_000;
const PREVIEW_TICK_MS = 200;

function Runner({
  replay,
  choice,
  onChoose,
  started,
  onStarted,
}: {
  replay: Replay;
  choice: ScenarioChoice;
  onChoose: (choice: ScenarioChoice) => void;
  started: boolean;
  onStarted: (value: boolean) => void;
}) {
  const transport = useReplay(replay);
  // Presentation mode. It removes the furniture that exists to drive the page and keeps the
  // things being filmed: the clock, the beat, the entry, the controls, and every panel. Nothing
  // it hides is data.
  const [presenting, setPresenting] = useState(false);
  // True only for the length of the dissolve, so the scrim and the copy can fade together while
  // the board underneath is already at frame zero.
  const [leaving, setLeaving] = useState(false);
  /*
   * Commentary on or off. On by default and remembered for the session, so somebody who turned it
   * off does not have it come back when they change recording, and somebody who reloads gets it
   * again because a reload is a new visitor as far as this page is concerned.
   */
  const [commentary, setCommentary] = useState(
    () => sessionStorage.getItem("salvage.commentary") !== "off",
  );
  useEffect(() => {
    sessionStorage.setItem("salvage.commentary", commentary ? "on" : "off");
  }, [commentary]);
  const state = useMemo(() => stateAt(replay, transport.ord), [replay, transport.ord]);
  const stage = stageOf(state);
  const meta = replay.recording.meta;

  /*
   * The board is not still while the curtain is up.
   *
   * A ninety second slice of the recording, seeked in place on a timer and looped, so the health
   * panel behind the scrim is moving the moment the page loads. It reads the same recording the
   * run reads and drives the same cursor, which is why it needs no separate animation state and
   * cannot drift from the data.
   *
   * It stops the moment the visitor presses, and it does not run while they are pressing: the
   * dissolve has already seeked to frame zero and a tick landing after that would drag the head
   * back into the preview.
   */
  const { seekTo } = transport;
  useEffect(() => {
    if (started || leaving) return;
    const from = replay.start;
    const to = Math.min(replay.end, from + PREVIEW_SIM_SECONDS);
    const began = performance.now();
    const id = window.setInterval(() => {
      const through = ((performance.now() - began) % PREVIEW_REAL_MS) / PREVIEW_REAL_MS;
      seekTo(from + (to - from) * through);
    }, PREVIEW_TICK_MS);
    return () => window.clearInterval(id);
  }, [started, leaving, replay.start, replay.end, seekTo]);

  // Filming shortcuts. Space starts and stops, the arrows walk entries, the brackets jump between
  // beats, and R restarts. Kept off any element that takes text so nothing is stolen from a field.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      // Guarded on the element interface rather than on truthiness: an event dispatched at the
      // window has a target with no tagName and no getAttribute, and reading through it threw.
      const target = event.target;
      if (target instanceof HTMLElement) {
        if (["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName)) return;
        if (target.getAttribute("role") === "slider") return;
      }
      switch (event.key) {
        case " ":
          event.preventDefault();
          transport.toggle();
          break;
        case "ArrowRight":
          event.preventDefault();
          transport.step(1);
          break;
        case "ArrowLeft":
          event.preventDefault();
          transport.step(-1);
          break;
        case "]":
          event.preventDefault();
          transport.stepBeat(1);
          break;
        case "[":
          event.preventDefault();
          transport.stepBeat(-1);
          break;
        case "r":
        case "R":
          event.preventDefault();
          transport.restart();
          break;
        case "p":
        case "P":
          event.preventDefault();
          setPresenting((current) => !current);
          break;
        default:
          break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [transport]);

  const fault = replay.faults[0] ?? null;
  const detectSeconds =
    fault && state.incident ? state.incident.openedAt - fault.start : null;
  const narration = narrate(replay, state, transport.ts, transport.inGap !== null);

  return (
    <div className="ov rp">
      {!started && (
        <Entry
          replay={replay}
          leaving={leaving}
          onStart={() => {
            // One transition. The scrim and the copy go together over 400ms, and the board is
            // already where it needs to be by the time they have gone: the loop stops and the head
            // returns to frame zero on the press, not at the end of the fade.
            setLeaving(true);
            transport.seekTo(replay.start);
            window.setTimeout(() => {
              onStarted(true);
              transport.play();
            }, CURTAIN_FADE_MS);
          }}
        />
      )}

      <Commentary replay={replay} ord={transport.ord} enabled={started && commentary} />

      <Transport
        replay={replay}
        transport={transport}
        commentary={commentary}
        onToggleCommentary={() => setCommentary((on) => !on)}
        choice={choice}
        onChoose={onChoose}
        presenting={presenting}
        onTogglePresenting={() => setPresenting((current) => !current)}
      />

      {/* Hidden in presentation mode with the rest of the driving furniture: by the time this is
          being filmed the explanation is in the voiceover, and the panels need the height.
          Hidden under the curtain too, where the headline is the title and the page's own heading
          and prose would otherwise read through the scrim directly behind it. */}
      {!presenting && started && (
      <div className="px-[var(--page-pad-x)] pt-[var(--space-4)]">
        <PageIntro
          title="Scenario Runner"
          what="A run that already happened, replayed from the record it left behind. Every frame on this page is recorded data."
          use="Press play, or step one entry at a time. Beat jumps to the next moment worth reading. The scrub bar seeks anywhere in the run, and P hides the controls for filming."
          shows={[
            ["What is happening", "one sentence saying what the run is doing right now, in plain English. If you read nothing else on this page, read that"],
            ["Sim time", "the whole run on one bar. Red is the fault, the rule along the top is the incident, and the ticks are the moments the replay pauses on"],
            ["Incident", "where this incident has reached, and how long the detector took to notice the fault"],
            ["Payment health", "each segment against its own baseline, moving one detector window at a time as the clock advances"],
            ["Diagnosis", "the rules verdict and the model verdict, then what they reconciled to, against the 0.6 threshold an action needs"],
            ["Plan and gates", "what the agent decided to do, then every rule each action was checked against and which one decided it"],
            ["Cases and outcomes", "the affected orders and where each ended up"],
          ]}
          caveat="Where the run did not record something, this page shows nothing rather than a guess. Both input confidences read 'not recorded' for that reason, and a segment with too little traffic is drawn empty."
        />
      </div>
      )}

      <Section title="What is happening" tight>
        <p className="narration" key={narration.key}>
          {narration.text}
        </p>
      </Section>

      <Section title="Sim time" tight>
        <Scrubber
          replay={replay}
          ts={transport.ts}
          onSeek={transport.seekTo}
          chrome={!presenting}
        />
      </Section>

      <Section
        anchor="incident"
        title="Incident"
        right={
          <span className="flex flex-wrap items-center gap-3">
            {state.incident && (
              <span className="note mono">{state.incident.id}</span>
            )}
            <span className="note">{choice.blurb}</span>
          </span>
        }
      >
        <Track state={state} stage={stage} />

        <div className="col2 mt-5">
          <div className="panel p-4">
            {state.incident ? (
              <div className="kv">
                <span className="lbl">Segment</span>
                <span className="mono mid text-[length:var(--fs-meta)]">{state.incident.segmentKey}</span>
                <span className="lbl">Affected scope</span>
                <span className="mono mid text-[length:var(--fs-meta)]">
                  {state.incident.scope.join(", ") || "-"}
                </span>
                <span className="lbl">Opened</span>
                <span className="mono mid text-[length:var(--fs-meta)]">
                  {timestamp(state.incident.openedAt)}
                </span>
                <span className="lbl">Detection latency</span>
                <span className="mono mid text-[length:var(--fs-meta)]">
                  {detectSeconds === null
                    ? "no recorded fault to measure from"
                    : `${Math.round(detectSeconds / 60)} sim minutes after the fault started`}
                </span>
                <span className="lbl">At risk when opened</span>
                <span className="mono mid text-[length:var(--fs-meta)]">
                  {rupeesShort(state.incident.atRisk)}
                </span>
                <span className="lbl">Closed</span>
                <span className="mono mid text-[length:var(--fs-meta)]">
                  {state.incident.closedAt === null
                    ? "still open"
                    : timestamp(state.incident.closedAt)}
                </span>
              </div>
            ) : (
              <p className="note">
                Nothing open. The detector needs the four conditions to hold in two consecutive
                windows before it opens anything.
              </p>
            )}
          </div>
          <div>
            {state.escalation && (
              <div className="notice notice-danger">
                <div className="notice-label">Escalated at {timeOnly(state.escalation.ts)}</div>
                <div className="notice-body">{state.escalation.reason}</div>
              </div>
            )}
          </div>
        </div>
      </Section>

      <Section
        anchor="health"
        title="Payment health"
        right={<span className="note">success rate against each segment&rsquo;s own baseline</span>}
      >
        <Health replay={replay} ts={transport.ts} incident={state.incident} />
      </Section>

      <Section
        anchor="diagnosis"
        title="Diagnosis"
        right={
          state.diagnosis && (
            <span className="note">
              rules, model and the reconciliation, all recorded in one entry at{" "}
              {timeOnly(state.diagnosis.ts)}
            </span>
          )
        }
      >
        <Diagnosis diagnosis={state.diagnosis} meta={meta} />
      </Section>

      <Section
        anchor="gates"
        title="Plan and gates"
        right={
          <span className="note">
            {count(state.actions.length)} action
            {state.actions.length === 1 ? "" : "s"} evaluated so far
          </span>
        }
      >
        <Gates state={state} meta={meta} />
      </Section>

      <Section anchor="cases" title="Cases and outcomes">
        <Cases state={state} />
      </Section>

      <Section
        title="Ledger"
        right={
          <span className="note mono">
            {replay.recording.ledger.length} entries in the chain
          </span>
        }
      >
        <Tail frames={state.tail} currentOrd={transport.ord} />
        <p className="note mt-3">{PROVES}</p>
      </Section>

      <Section title="Provenance" tight>
        <div className="kv">
          <span className="lbl">Run</span>
          <span className="mono mid text-[length:var(--fs-meta)]">{meta.run_id}</span>
          <span className="lbl">Captured from</span>
          <span className="mono mid text-[length:var(--fs-meta)]">
            salvage agent run --scenario {meta.scenario} --seed {meta.seed} --policy {meta.policy}{" "}
            --provider {meta.provider}
          </span>
          <span className="lbl">Params hash</span>
          <span className="mono mid text-[length:var(--fs-meta)]">{meta.params_hash.slice(0, 16)}</span>
          <span className="lbl">Source revision</span>
          <span className="mono mid text-[length:var(--fs-meta)]">{meta.git_rev || "not recorded"}</span>
          <span className="lbl">Observed window</span>
          <span className="mono mid text-[length:var(--fs-meta)]">
            {timestamp(replay.start)} to {timestamp(replay.end)}, {elapsed(replay.start, replay.end)}{" "}
            of sim time
          </span>
        </div>
        <p className="note mt-3">{replay.recording._note}</p>
        <p className="note mt-2">
          Nothing on this page is live. The world it describes finished before the page loaded. To
          run a scenario for real, use the CLI; to read the record afterwards, the{" "}
          <Link to="/ledger" className="link focus-ring">
            Ledger
          </Link>{" "}
          and{" "}
          <Link to="/results" className="link focus-ring">
            Results
          </Link>{" "}
          pages read the live database.
        </p>
        <p className="note mt-2">
          Keys: space plays and pauses, the arrow keys walk one entry, the bracket keys jump
          between beats, R restarts, and P is presentation mode.
        </p>
      </Section>
    </div>
  );
}
