import { useEffect, useState } from "react";
import type { Replay } from "../../replay/model";
import type { Speed, Transport as TransportApi } from "../../replay/useReplay";
import { PROVES, verifyChain, type VerifyResult } from "../../replay/verify";
import { SCENARIOS, type ScenarioChoice } from "../../replay/load";
import { shortHash, timestamp } from "../../lib/format";
import { elapsed } from "../../lib/health";

/**
 * The transport: what is being replayed, where the head is, and the controls that move it.
 *
 * Three tiers, because on camera the eye has to land somewhere first. The sim clock is the read:
 * it is the largest thing here and it is what the whole page is a function of. The entry kind and
 * its reference are next, because they say what the frame the head is on actually is. The
 * sequence, the hash and the position are last and muted; they are provenance, checked once and
 * then ignored, and at equal weight they were competing with the clock for attention.
 *
 * The speed multipliers are stated in the units they actually mean. 1x is one sim minute per real
 * second, which is one detector window step, so at 1x the traffic panel advances once a second.
 * Saying so on the control matters, because "1x" against a simulator clock could equally mean one
 * sim second per second, and that would be three hours of watching for the interesting part.
 */

const SPEEDS: { value: Speed; label: string; hint: string }[] = [
  { value: "1x", label: "1x", hint: "1 sim minute per second" },
  { value: "10x", label: "10x", hint: "10 sim minutes per second" },
  { value: "60x", label: "60x", hint: "1 sim hour per second" },
  { value: "step", label: "Step", hint: "one entry per press" },
];

export function Transport({
  replay,
  transport,
  choice,
  onChoose,
  presenting,
  onTogglePresenting,
}: {
  replay: Replay;
  transport: TransportApi;
  choice: ScenarioChoice;
  onChoose: (choice: ScenarioChoice) => void;
  presenting: boolean;
  onTogglePresenting: () => void;
}) {
  const meta = replay.recording.meta;
  const frame = replay.frames[Math.min(transport.ord, replay.frames.length - 1)];
  const total = replay.playTo - replay.playFrom + 1;
  const position = Math.min(total, Math.max(0, transport.ord - replay.playFrom + 1));

  return (
    <div className="transport">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {!presenting && (
          <>
            <label className="flex items-center gap-2">
              <span className="lbl">Recording</span>
              <select
                className="field focus-ring"
                value={choice.id}
                onChange={(event) => {
                  const next = SCENARIOS.find((entry) => entry.id === event.target.value);
                  if (next) onChoose(next);
                }}
              >
                {SCENARIOS.map((entry) => (
                  <option key={entry.id} value={entry.id}>
                    {entry.label}
                  </option>
                ))}
              </select>
            </label>

            <span className="lbl">
              seed <span className="lbl-2">{meta.seed}</span>
            </span>
            <span className="lbl">
              variant <span className="lbl-2">{meta.variant}</span>
            </span>
            <span className="lbl">
              policy <span className="lbl-2">{meta.policy}</span>
            </span>
          </>
        )}

        <span className={`flex flex-wrap items-center gap-2${presenting ? "" : " ml-auto"}`}>
          <div className="segment" role="group" aria-label="Speed">
            {SPEEDS.map((speed) => (
              <button
                key={speed.value}
                type="button"
                title={speed.hint}
                aria-pressed={transport.speed === speed.value}
                onClick={() => transport.setSpeed(speed.value)}
                className="focus-ring"
              >
                {speed.label}
              </button>
            ))}
          </div>

          <button
            type="button"
            className="btn btn-primary focus-ring"
            onClick={transport.toggle}
            disabled={transport.speed === "step" || transport.atEnd}
          >
            {transport.playing ? "Pause" : "Play"}
          </button>
          <button
            type="button"
            className="btn focus-ring"
            onClick={() => transport.step(-1)}
            title="Previous entry"
          >
            &larr; Entry
          </button>
          <button
            type="button"
            className="btn focus-ring"
            onClick={() => transport.step(1)}
            title="Next entry"
          >
            Entry &rarr;
          </button>
          <button
            type="button"
            className="btn focus-ring"
            onClick={() => transport.stepBeat(1)}
            title="Jump to the next beat"
          >
            Beat &rarr;
          </button>
          <button type="button" className="btn focus-ring" onClick={transport.restart}>
            Restart
          </button>
          <button
            type="button"
            className="btn focus-ring"
            aria-pressed={presenting}
            onClick={onTogglePresenting}
            title="Presentation mode, P"
          >
            {presenting ? "Exit present" : "Present"}
          </button>
          <VerifyControl replay={replay} />
        </span>
      </div>

      {/* Primary: the clock, then what the head is on. */}
      <div className="mt-3 flex flex-wrap items-baseline gap-x-5 gap-y-2">
        <span className="flex items-baseline gap-2">
          <span className="lbl">Sim clock</span>
          <span className="fig-lg">{timestamp(Math.round(transport.ts))}</span>
          <span className="note">IST</span>
        </span>
        {frame && (
          <span className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="mono mid text-[length:var(--fs-meta)]">{frame.kind}</span>
            <span className="mono dim truncate text-[length:var(--fs-meta)]">{frame.refId}</span>
          </span>
        )}
        {replay.faults.length > 0 && (
          <span className="flex items-baseline gap-2">
            <span className="lbl">Since fault</span>
            <span className="mono mid text-[length:var(--fs-meta)]">
              {transport.ts >= replay.faults[0].start
                ? elapsed(replay.faults[0].start, Math.round(transport.ts))
                : "not started"}
            </span>
          </span>
        )}
        {frame?.held && (
          <span className="chip info">
            <span className="dot" aria-hidden="true" />
            {transport.holding ? "holding" : "beat"} &middot; {frame.holdLabel}
          </span>
        )}
      </div>

      {/* Tertiary: provenance. Checked once, then ignored, so it is the smallest thing here. */}
      {!presenting && frame && (
        <div className="mt-1.5 flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <span className="tert">
            position {position} / {total}
          </span>
          {frame.seq !== null && <span className="tert">seq {frame.seq}</span>}
          {frame.hash && <span className="tert">{shortHash(frame.hash, 12)}</span>}
          {frame.source === "cases" && (
            <span className="tert">read from the case table, not the chain</span>
          )}
        </div>
      )}

      {transport.inGap && (
        <div className="wait mt-3">
          <div className="lbl warn">The agent does nothing here</div>
          <div className="txt mt-1">
            No ledger entry between {timestamp(transport.inGap.start)} and{" "}
            {timestamp(transport.inGap.end)}, a stretch of{" "}
            <span className="mono">
              {elapsed(transport.inGap.start, transport.inGap.end)}
            </span>{" "}
            of sim time. Traffic keeps flowing and the health panel keeps moving through it, because
            the detector is still measuring; what stops is the agent. On this run the long one is
            quiet hours: sends that passed every other gate are held from{" "}
            {meta.thresholds.quiet_hours_start}:00 until{" "}
            {String(meta.thresholds.quiet_hours_end).padStart(2, "0")}:00 and go out then. The head
            crosses it rather than skipping it, faster than the multiplier, so the wait is visible
            without being sat through.
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * The verify control.
 *
 * The recording keeps every entry's `payload_json` as the exact string its hash commits to, so the
 * chain can be recomputed here from the fixture alone, with no server and no re-serialisation.
 * This is the same computation `salvage ledger verify` runs.
 */
function VerifyControl({ replay }: { replay: Replay }) {
  const [result, setResult] = useState<VerifyResult | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setResult(null);
  }, [replay]);

  const run = async () => {
    setBusy(true);
    try {
      setResult(await verifyChain(replay.recording.ledger, replay.recording.meta.genesis_hash));
    } catch (error) {
      setResult({
        ok: false,
        entries: replay.recording.ledger.length,
        headHash: null,
        brokenSeq: null,
        detail: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <span className="flex items-baseline gap-2.5">
      <button type="button" className="btn focus-ring" onClick={run} disabled={busy}>
        {busy ? "Verifying" : "Verify chain"}
      </button>
      {result && (
        <span className="flex items-baseline gap-2" title={PROVES}>
          <span className={`chip ${result.ok ? "ok" : "crit"}`}>
            <span className="dot" aria-hidden="true" />
            {result.ok ? "chain intact" : `broken at ${result.brokenSeq}`}
          </span>
          <span className="tert">
            {result.entries} entries
            {result.headHash ? ` · head ${shortHash(result.headHash, 12)}` : ""}
          </span>
        </span>
      )}
    </span>
  );
}
