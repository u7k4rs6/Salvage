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
import { SCENARIOS, loadReplay, type ScenarioChoice } from "../replay/load";
import type { Replay } from "../replay/model";
import { stateAt, stageOf } from "../replay/state";
import { useReplay } from "../replay/useReplay";
import { PROVES } from "../replay/verify";
import { count, rupeesShort, timeOnly, timestamp } from "../lib/format";
import { elapsed } from "../lib/health";
import "./overview.css";
import "./replay.css";

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

  return <Runner key={choice.id} replay={replay} choice={choice} onChoose={setChoice} />;
}

function Runner({
  replay,
  choice,
  onChoose,
}: {
  replay: Replay;
  choice: ScenarioChoice;
  onChoose: (choice: ScenarioChoice) => void;
}) {
  const transport = useReplay(replay);
  // Presentation mode. It removes the furniture that exists to drive the page and keeps the
  // things being filmed: the clock, the beat, the entry, the controls, and every panel. Nothing
  // it hides is data.
  const [presenting, setPresenting] = useState(false);
  const state = useMemo(() => stateAt(replay, transport.ord), [replay, transport.ord]);
  const stage = stageOf(state);
  const meta = replay.recording.meta;

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

  return (
    <div className="ov rp">
      <Transport
        replay={replay}
        transport={transport}
        choice={choice}
        onChoose={onChoose}
        presenting={presenting}
        onTogglePresenting={() => setPresenting((current) => !current)}
      />

      <Section title="Sim time" tight>
        <Scrubber
          replay={replay}
          ts={transport.ts}
          onSeek={transport.seekTo}
          chrome={!presenting}
        />
      </Section>

      <Section
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
                <span className="mono mid text-[12px]">{state.incident.segmentKey}</span>
                <span className="lbl">Affected scope</span>
                <span className="mono mid text-[12px]">
                  {state.incident.scope.join(", ") || "-"}
                </span>
                <span className="lbl">Opened</span>
                <span className="mono mid text-[12px]">
                  {timestamp(state.incident.openedAt)}
                </span>
                <span className="lbl">Detection latency</span>
                <span className="mono mid text-[12px]">
                  {detectSeconds === null
                    ? "no recorded fault to measure from"
                    : `${Math.round(detectSeconds / 60)} sim minutes after the fault started`}
                </span>
                <span className="lbl">At risk when opened</span>
                <span className="mono mid text-[12px]">
                  {rupeesShort(state.incident.atRisk)}
                </span>
                <span className="lbl">Closed</span>
                <span className="mono mid text-[12px]">
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
              <div className="alert">
                <div className="lbl warn">Escalated at {timeOnly(state.escalation.ts)}</div>
                <div className="txt mt-1">{state.escalation.reason}</div>
              </div>
            )}
          </div>
        </div>
      </Section>

      <Section
        title="Payment health"
        right={<span className="note">success rate against each segment&rsquo;s own baseline</span>}
      >
        <Health replay={replay} ts={transport.ts} incident={state.incident} />
      </Section>

      <Section
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

      <Section title="Cases and outcomes">
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
          <span className="mono mid text-[12px]">{meta.run_id}</span>
          <span className="lbl">Captured from</span>
          <span className="mono mid text-[12px]">
            salvage agent run --scenario {meta.scenario} --seed {meta.seed} --policy {meta.policy}{" "}
            --provider {meta.provider}
          </span>
          <span className="lbl">Params hash</span>
          <span className="mono mid text-[12px]">{meta.params_hash.slice(0, 16)}</span>
          <span className="lbl">Source revision</span>
          <span className="mono mid text-[12px]">{meta.git_rev || "not recorded"}</span>
          <span className="lbl">Observed window</span>
          <span className="mono mid text-[12px]">
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
