import type { Frame, Replay } from "./model";
import { decidingRule } from "./model";
import type { ActionPayload } from "./types";
import { rupees, timeOnly } from "../lib/format";
import { faultInEnglish } from "./narrate";

/**
 * What to say over a beat, and where to point while saying it.
 *
 * The beats are the fourteen the Beat walk already stops on, so this adds no new notion of what is
 * worth reading. It only decides whether a given beat has something sayable and, if so, says it in
 * one sentence.
 *
 * Every number in every sentence is read off the frame that triggered it, or off the run's own
 * thresholds. Nothing is written down here that the recording does not carry: a beat whose payload
 * lacks what the sentence would need returns null and gets no mark. That is the whole reason this
 * is a function of the frame rather than a table of strings keyed by kind.
 */

export interface Mark {
  /** The frame this is about. Also the identity, so the same beat is never queued twice. */
  ord: number;
  /** `data-anchor` on the region to point at. */
  anchor: string;
  /** Mono microlabel, the same register as the rest of the machine-written tier. */
  label: string;
  sentence: string;
}

/** Whole minutes, for a sentence rather than for a readout. */
function minutesBetween(from: number, to: number): number {
  return Math.max(1, Math.round((to - from) / 60));
}

export function markFor(replay: Replay, frame: Frame): Mark | null {
  const at = (ts: number) => timeOnly(ts);
  const thresholds = replay.recording.meta.thresholds;
  const fault = replay.faults[0] ?? null;
  const payload = frame.payload as Record<string, unknown>;

  switch (frame.kind) {
    case "detect.incident.opened": {
      // The segment in English rather than as its key: `card:card_bin6:411111` is the identifier,
      // and it is already on the board two lines below this mark.
      if (typeof payload.segment_key !== "string" || !fault) return null;
      const late = minutesBetween(fault.start, frame.ts);
      return {
        ord: frame.ord,
        anchor: "incident",
        label: "Detected",
        sentence: `${faultInEnglish(fault.selector)} were failing far more than normal, so the detector opened an incident. ${late} minutes after the fault started.`,
      };
    }

    case "detect.incident.closed":
      return {
        ord: frame.ord,
        anchor: "incident",
        label: "Closed",
        sentence: `The incident closed at ${at(frame.ts)}. The detector stopped seeing the segment fail.`,
      };

    case "diagnose.reconciled": {
      const confidence = typeof payload.confidence === "number" ? payload.confidence : null;
      if (confidence === null) return null;
      const agreed = payload.agreed === true;
      const floor = thresholds.action_confidence;
      return {
        ord: frame.ord,
        anchor: "diagnosis",
        label: "Diagnosed",
        sentence: agreed
          ? `Rules and model reached the same cause, at confidence ${confidence.toFixed(2)} against a threshold of ${floor}. High enough to act on.`
          : `Rules and model disagreed, so the reconciler decided, at confidence ${confidence.toFixed(2)} against a threshold of ${floor}.`,
      };
    }

    case "decide.plan": {
      const eligibility = payload.eligibility as Record<string, number> | undefined;
      if (!eligibility || typeof eligibility.affected_orders !== "number") return null;
      return {
        ord: frame.ord,
        anchor: "gates",
        label: "Planned",
        sentence: `${eligibility.affected_orders} orders were caught by this incident, and ${eligibility.consented} of those customers had already agreed to be contacted.`,
      };
    }

    case "execute.steer_recovered": {
      const amount = typeof payload.amount === "number" ? payload.amount : null;
      if (amount === null) return null;
      return {
        ord: frame.ord,
        anchor: "cases",
        label: "Recovered",
        sentence: `A shopper steered onto a working method paid \u20b9${rupees(amount)}. No message was sent to do it.`,
      };
    }

    case "execute.link_paid": {
      const amount = typeof payload.amount === "number" ? payload.amount : null;
      if (amount === null) return null;
      return {
        ord: frame.ord,
        anchor: "cases",
        label: "Recovered",
        sentence: `Someone paid \u20b9${rupees(amount)} through a recovery link at ${at(frame.ts)}.`,
      };
    }

    case "channel.opt_out": {
      const nudge = typeof payload.nudge_number === "number" ? payload.nudge_number : null;
      return {
        ord: frame.ord,
        anchor: "cases",
        label: "Opted out",
        sentence: nudge
          ? `A customer opted out after message ${nudge}. Nothing else is ever sent to them.`
          : "A customer opted out. Nothing else is ever sent to them.",
      };
    }

    // The two states the ledger cannot record, read out of the case table instead.
    case "case.abandoned":
      return {
        ord: frame.ord,
        anchor: "cases",
        label: "Abandoned",
        sentence:
          "This order was never paid. The ledger has no entry for that, so it is read from the case table.",
      };

    case "case.paid_elsewhere":
      return {
        ord: frame.ord,
        anchor: "cases",
        label: "Paid elsewhere",
        sentence:
          "This order was paid another way. Salvage did not recover it, and the ledger has no entry for it.",
      };

    default:
      break;
  }

  // Actions. What is worth saying is which rule decided, so the sentence comes off the gate that
  // failed rather than off the kind.
  if (frame.kind.startsWith("execute.action.")) {
    const action = frame.payload as ActionPayload;
    const decided = decidingRule(action.gates ?? []);
    const status = frame.kind.slice("execute.action.".length);

    if (status === "executed") {
      return {
        ord: frame.ord,
        anchor: "gates",
        label: "Acted",
        sentence: `Every gate passed, so ${action.type ?? "the action"} ran. This is the first thing the agent actually did.`,
      };
    }

    if (!decided) return null;

    switch (decided.rule) {
      case "customer.consent":
        return {
          ord: frame.ord,
          anchor: "gates",
          label: "Refused",
          sentence:
            "This send was refused. The customer never agreed to be contacted, and no other rule can override that.",
        };
      case "customer.incident_cap":
        return {
          ord: frame.ord,
          anchor: "gates",
          label: "Refused",
          sentence: `Refused. This customer had already had ${thresholds.max_nudges_per_incident} messages for this incident, which is the cap.`,
        };
      case "timing.not_quiet_hours":
        return {
          ord: frame.ord,
          anchor: "gates",
          label: "Queued",
          sentence: `It is past ${thresholds.quiet_hours_start}:00, so this send is held until ${String(thresholds.quiet_hours_end).padStart(2, "0")}:00 rather than cancelled.`,
        };
      case "timing.method_not_still_degraded":
        return {
          ord: frame.ord,
          anchor: "gates",
          label: "Deferred",
          sentence:
            "Deferred. The method had recovered by the time this was checked, so there was nothing to steer away from.",
        };
      default:
        return {
          ord: frame.ord,
          anchor: "gates",
          label: status.charAt(0).toUpperCase() + status.slice(1),
          sentence: `${decided.rule} decided this one: ${decided.detail}`,
        };
    }
  }

  // Anything else is a beat with nothing to say about it, and gets no mark.
  return null;
}

/**
 * How long a mark stays up.
 *
 * Reading time, not a fixed number, and it does not shrink with the speed multiplier: at 60x a
 * sentence still takes as long to read as it does at 1x. A cluster of beats sharing one sim second
 * therefore queues rather than flashing past, which is what the queue in Commentary is for.
 */
export function holdMsFor(mark: Mark): number {
  const words = mark.sentence.trim().split(/\s+/).length;
  return Math.min(6200, Math.max(2800, 1200 + words * 190));
}
