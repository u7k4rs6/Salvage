import type { DiagnosisRecord } from "../../replay/state";
import type { RecordingMeta } from "../../replay/types";
import { causeLabel, count, percent, timeOnly } from "../../lib/format";

/**
 * The two verdicts and the one they reconcile to.
 *
 * All three land together, in one entry, at one sim second, and the page shows them that way. The
 * run recorded no separate arrival times for them because none elapsed, so staging them as three
 * arrivals would be putting time into the picture that the system did not spend.
 *
 * Neither input carries a confidence and neither panel shows one. The rules verdict has none by
 * design. The model's own number is consumed by reconciliation, which lifts agreement to at least
 * 0.7 and pushes disagreement to at most 0.5, and only the result is written down. Those cells are
 * blank rather than filled with the reconciled number wearing two other hats.
 */

export function Diagnosis({
  diagnosis,
  meta,
}: {
  diagnosis: DiagnosisRecord | null;
  meta: RecordingMeta;
}) {
  if (!diagnosis) {
    return (
      <div className="panel p-4">
        <p className="note">
          Not diagnosed yet. Rules and model are asked once, when the incident opens.
        </p>
      </div>
    );
  }

  const threshold = meta.thresholds.action_confidence;
  const clears = diagnosis.confidence >= threshold;

  return (
    <div>
      <div className="col2">
        <Verdict
          label="Rules"
          cause={diagnosis.rulesCause}
          prose={diagnosis.rulesDetail}
          note="The rules carry no confidence of their own. Nothing is recorded here because nothing was."
        />
        <Verdict
          label="Model"
          cause={diagnosis.llmCause}
          prose={diagnosis.rationale}
          note="The model's own confidence is consumed by reconciliation and not written down, so this is blank rather than guessed."
        />
      </div>

      <div className="panel mt-4 p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <span className="lbl">Reconciled</span>
          <span className="note mono">{timeOnly(diagnosis.ts)}</span>
        </div>
        <div className="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-2">
          <span className="fig-lg">{causeLabel(diagnosis.rootCause)}</span>
          <span className={`chip ${diagnosis.agreed === true ? "ok" : diagnosis.agreed === false ? "crit" : "warn"}`}>
            <span className="dot" aria-hidden="true" />
            {diagnosis.agreed === true
              ? "rules and model agree"
              : diagnosis.agreed === false
                ? "rules and model disagree"
                : "no model verdict"}
          </span>
        </div>

        <div className="mt-4">
          <div className="flex items-baseline justify-between">
            <span className="lbl">Confidence</span>
            <span className="fig-md">{diagnosis.confidence.toFixed(2)}</span>
          </div>
          <div className="conf mt-2" role="img" aria-label={`confidence ${diagnosis.confidence.toFixed(2)} against the ${threshold} action threshold`}>
            <div
              className="conf-fill"
              style={{
                width: `${Math.max(0, Math.min(1, diagnosis.confidence)) * 100}%`,
                background: clears ? "var(--success)" : "var(--warning)",
                opacity: 0.55,
              }}
            />
            <div className="conf-threshold" style={{ left: `${threshold * 100}%` }} />
          </div>
          <div className="mt-1.5 flex items-baseline justify-between">
            <span className="note mono">0.00</span>
            <span className={`note mono ${clears ? "ok" : "warn"}`}>
              {threshold.toFixed(1)} action threshold
            </span>
            <span className="note mono">1.00</span>
          </div>
          <p className="note mt-2">
            {clears
              ? `Above ${threshold}, so a customer-facing action is allowed to be proposed. Every gate ladder still has to pass after that.`
              : `Below ${threshold}, so nothing customer-facing can be proposed and the incident escalates.`}
          </p>
        </div>

        {diagnosis.escalate && diagnosis.escalationReason && (
          <div className="notice notice-danger mt-4">
            <div className="notice-label">Escalating</div>
            <div className="notice-body">{diagnosis.escalationReason}</div>
          </div>
        )}
      </div>

      <Evidence evidence={diagnosis.evidence} />
    </div>
  );
}

function Verdict({
  label,
  cause,
  prose,
  note,
}: {
  label: string;
  cause: string | null;
  prose: string;
  note: string;
}) {
  return (
    <div className="panel p-4">
      <div className="lbl">{label}</div>
      <div className="fig-md mt-2">{cause ? causeLabel(cause) : "no verdict"}</div>
      <div className="mt-3 flex items-baseline gap-3">
        <span className="lbl">Confidence</span>
        {/* Not recorded. Shown as absent, which is what it is. */}
        <span className="mono dim text-[length:var(--fs-meta)]">not recorded</span>
      </div>
      {prose && <p className="txt mt-3">{prose}</p>}
      <p className="note mt-3">{note}</p>
    </div>
  );
}

/**
 * The evidence packet, exactly as the model saw it.
 *
 * Carried whole on the `diagnose.reconciled` entry, so this is the input to the verdict above and
 * not a summary of it. It has no contact detail, no name and no order note in it by construction.
 */
function Evidence({ evidence }: { evidence: DiagnosisRecord["evidence"] }) {
  const top = (dist: Record<string, number>) =>
    Object.entries(dist)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 4);

  return (
    <details className="mt-4 group">
      <summary className="lbl focus-ring cursor-pointer list-none hover:text-[color:var(--text-secondary)]">
        Evidence packet, as the model received it
      </summary>
      <div className="panel mt-2 p-4">
        <div className="kv">
          <span className="lbl">Segment</span>
          <span className="mono mid text-[length:var(--fs-meta)]">{evidence.segment_key}</span>
          <span className="lbl">Scope</span>
          <span className="mono mid text-[length:var(--fs-meta)]">{evidence.affected_scope.join(", ") || "-"}</span>
          <span className="lbl">Window</span>
          <span className="mono mid text-[length:var(--fs-meta)]">
            {timeOnly(evidence.window_start)} to {timeOnly(evidence.window_end)}
          </span>
          <span className="lbl">Attempts</span>
          <span className="mono mid text-[length:var(--fs-meta)]">{count(evidence.attempts)}</span>
          <span className="lbl">Failure rate</span>
          <span className="mono mid text-[length:var(--fs-meta)]">
            {percent(evidence.rate)} against a {percent(evidence.baseline_rate)} baseline
          </span>
          <span className="lbl">Excess failures</span>
          <span className="mono mid text-[length:var(--fs-meta)]">{evidence.excess_failures.toFixed(1)}</span>
          <span className="lbl">Share of volume</span>
          <span className="mono mid text-[length:var(--fs-meta)]">
            {percent(evidence.share_of_merchant_volume)}
          </span>
          <span className="lbl">Trend</span>
          <span className="mono mid text-[length:var(--fs-meta)]">{evidence.trend}</span>
          <span className="lbl">Config changed</span>
          <span className="mono mid text-[length:var(--fs-meta)]">
            {evidence.merchant_config_changed_recently ? "yes, recently" : "no"}
          </span>
          <span className="lbl">Minutes since onset</span>
          <span className="mono mid text-[length:var(--fs-meta)]">{evidence.minutes_since_onset}</span>
        </div>

        <div className="col2 mt-4">
          <Dist label="Error source" rows={top(evidence.error_source_dist)} />
          <Dist label="Error reason" rows={top(evidence.error_reason_dist)} />
        </div>

        {evidence.sample_descriptions.length > 0 && (
          <div className="mt-4">
            <div className="lbl">Samples</div>
            <ul className="mt-1.5">
              {evidence.sample_descriptions.map((line, index) => (
                <li key={index} className="note mono">
                  {line}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </details>
  );
}

function Dist({ label, rows }: { label: string; rows: [string, number][] }) {
  return (
    <div>
      <div className="lbl">{label}</div>
      <div className="divide mt-1.5">
        {rows.length === 0 && <div className="note py-1.5">nothing recorded</div>}
        {rows.map(([name, share]) => (
          <div key={name} className="flex items-baseline justify-between gap-3 py-1.5">
            <span className="mono mid truncate text-[length:var(--fs-meta)]">{name}</span>
            <span className="mono note">{percent(share)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
