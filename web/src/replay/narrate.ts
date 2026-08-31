import type { Replay } from "./model";
import type { ReplayState } from "./state";

/**
 * One sentence, in plain English, saying what is happening right now.
 *
 * This is the layer that replaces somebody standing next to the screen explaining it. A visitor
 * who reads nothing else on the page should still be able to follow the run from this line alone,
 * so it uses no word the system invented: no segment, no gate, no incident id, no ledger. The
 * words are the ones a person who runs a shop would use.
 *
 * Everything in it is read off the recording. The numbers are counted from entries the replay has
 * consumed, the minutes are differences between recorded timestamps, and the causes and refusal
 * reasons are translations of recorded values into English, never a judgement about them. If the
 * run did not record something, the sentence does not mention it.
 */

/** Recorded root causes, in the words of somebody who is not a payments engineer. */
const CAUSE_IN_ENGLISH: Record<string, string> = {
  auth_failure_bin: "one range of card numbers is being turned down by the bank that issued them",
  issuer_outage: "the bank on the other end is having an outage",
  gateway_degradation: "the payment gateway itself is struggling",
  merchant_config: "a setting on the shop's own payment account is wrong",
  customer_side: "the failures are coming from the shoppers' own devices and apps",
  unknown: "it could not tell",
};

/** Recorded rule names, in the words of the person the rule protects. */
const RULE_IN_ENGLISH: Record<string, string> = {
  "customer.consent": "those shoppers never agreed to be contacted",
  "customer.not_opted_out": "those shoppers had asked not to be contacted",
  "customer.incident_cap": "those shoppers had already been contacted twice about this",
  "customer.rolling_7_day_cap": "those shoppers had already been contacted three times this week",
  "case.no_hard_decline": "those cards were refused outright, so a payment link would fail too",
  "case.order_unpaid": "those orders had already been paid",
  "case.within_ttl": "those orders were too old to reopen",
  "matrix.confidence_threshold": "it was not confident enough about the cause to act",
  "matrix.action_allowed_for_cause": "that action is not allowed for this cause",
  "timing.not_quiet_hours": "it is the middle of the night",
  "timing.method_not_still_degraded": "the payment route was still broken",
};

/** A recorded fault selector, said out loud. */
export function faultInEnglish(selector: Record<string, string>): string {
  if (selector.card_bin) return `cards starting ${selector.card_bin}`;
  if (selector.upi_handle) return `UPI payments through @${selector.upi_handle}`;
  if (selector.card_issuer) return `cards from ${selector.card_issuer}`;
  if (selector.nb_bank) return `bank transfers through ${selector.nb_bank}`;
  if (selector.method === "netbanking") return "bank transfers";
  if (selector.method) return `${selector.method} payments`;
  return "payments";
}

function minutes(seconds: number): string {
  const m = Math.max(0, Math.round(seconds / 60));
  if (m < 60) return `${m} minute${m === 1 ? "" : "s"}`;
  const h = Math.floor(m / 60);
  const rest = m % 60;
  return rest === 0 ? `${h} hour${h === 1 ? "" : "s"}` : `${h}h ${rest}m`;
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

export interface Narration {
  /** The sentence. */
  text: string;
  /** Which beat it belongs to, so the line can be keyed and not re-animated on every tick. */
  key: string;
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * The sentence is chosen by the entry the head is on first, and only then by the state of the run.
 *
 * That order matters and getting it wrong broke the most important beat on the page. The incident
 * closes at 22:42, but the fifty eight refusals, the hundred and one held sends and every payment
 * the next morning all happen at or after that moment. Ranking "the case is closed" above the
 * current entry meant the refusals were never narrated at all: the line said the story had ended
 * while the run was still going.
 */
export function narrate(replay: Replay, state: ReplayState, ts: number, inGap: boolean): Narration {
  const fault = replay.faults[0] ?? null;
  const thing = fault ? faultInEnglish(fault.selector) : "payments";
  const frame = state.frame;
  const recovered = state.recoveredByLink + state.recoveredBySteer;
  const refused = state.statusCounts.refused ?? 0;
  const taken = state.statusCounts.executed ?? 0;

  // -- what the head is on ------------------------------------------------

  if (frame && frame.kind.startsWith("execute.action.") && state.currentAction) {
    const action = state.currentAction;
    if (action.status === "refused" && action.decided) {
      const why = RULE_IN_ENGLISH[action.decided.rule] ?? "a rule it is not allowed to break";
      return {
        key: `refused:${action.decided.rule}`,
        text: `Salvage refused to act here, because ${why}. ${plural(refused, "refusal", "refusals")} so far.`,
      };
    }
    if (action.status === "queued") {
      return {
        key: "queued",
        text:
          "This one passed every check except the time of day, so it is held until nine in the " +
          "morning rather than sent now.",
      };
    }
    if (action.status === "deferred") {
      return {
        key: "deferred",
        text:
          `${capitalise(thing)} are still failing, so Salvage is holding back rather than sending ` +
          "shoppers into a payment route it knows is broken.",
      };
    }
    return {
      key: "acting",
      text: `Salvage is acting: ${plural(taken, "action", "actions")} taken, ${refused} refused.`,
    };
  }

  if (frame && (frame.kind === "execute.link_paid" || frame.kind === "execute.steer_recovered")) {
    return {
      key: "recovered",
      text: `A shopper just paid. ${plural(recovered, "sale", "sales")} recovered that would otherwise have been lost.`,
    };
  }

  if (frame && frame.kind === "channel.opt_out") {
    return {
      key: "optout",
      text: "A shopper asked not to be contacted again. Salvage recorded it and will not write to them.",
    };
  }

  if (frame && frame.kind === "escalation.opened") {
    return {
      key: "escalated",
      text:
        "Salvage stopped and handed this to a person. It is not allowed to contact shoppers about " +
        "a problem on the shop's own side, so it did nothing rather than something wrong.",
    };
  }

  if (frame && frame.kind === "detect.incident.closed") {
    const back = `${capitalise(thing)} went back to normal, so Salvage closed the case.`;
    return {
      key: "closed",
      text:
        recovered > 0
          ? `${back} ${plural(recovered, "shopper", "shoppers")} came back and paid.`
          : back,
    };
  }

  if (frame && frame.kind === "decide.plan" && state.plan) {
    const count = state.plan.plan.actions.length;
    return {
      key: "plan",
      text:
        `Salvage has a plan: ${plural(count, "thing", "things")} it wants to do. It can only ` +
        "choose from a fixed list, and every choice still has to pass its rules one by one.",
    };
  }

  if (frame && frame.kind === "diagnose.reconciled" && state.diagnosis) {
    const why = CAUSE_IN_ENGLISH[state.diagnosis.rootCause] ?? state.diagnosis.rootCause;
    const agreed =
      state.diagnosis.agreed === true
        ? " A rules engine and a language model looked at the same evidence and agreed."
        : state.diagnosis.agreed === false
          ? " The rules engine and the language model disagreed, which lowers its confidence."
          : "";
    return { key: "diagnosed", text: `Salvage worked out why: ${why}.${agreed}` };
  }

  if (frame && frame.kind === "detect.incident.opened" && state.incident) {
    const latency = fault ? state.incident.openedAt - fault.start : null;
    return {
      key: "detected",
      text:
        `Salvage noticed: ${thing} are failing far more often than they normally do` +
        (latency === null ? "." : `, ${minutes(latency)} after it started.`),
    };
  }

  // -- and otherwise, where the run has got to ----------------------------

  // A stretch with nothing in it is a thing the system did, not a pause in the video.
  if (inGap) {
    const queued = state.statusCounts.queued ?? 0;
    if (queued > 0) {
      return {
        key: "quiet",
        text:
          `It is the middle of the night. ${plural(queued, "payment link", "payment links")} are ` +
          "ready to go out and Salvage is holding all of them until nine in the morning.",
      };
    }
    return { key: "gap", text: "Nothing is happening. Salvage is watching and waiting." };
  }

  if (state.escalation) {
    return {
      key: "escalated",
      text:
        "Salvage handed this to a person and stopped. Nothing customer-facing happens until " +
        "somebody decides.",
    };
  }

  if (state.incident?.closedAt != null) {
    return {
      key: "settled",
      text:
        `${capitalise(thing)} are back to normal. ` +
        `${plural(taken, "action", "actions")} taken, ${refused} refused, ` +
        `${plural(recovered, "sale", "sales")} recovered.`,
    };
  }

  if (state.actions.length > 0) {
    return {
      key: "acting",
      text: `Salvage is acting: ${plural(taken, "action", "actions")} taken, ${refused} refused.`,
    };
  }

  if (state.incident) {
    return { key: "open", text: `Salvage is working on it. ${capitalise(thing)} are still failing.` };
  }

  if (fault && ts >= fault.start) {
    return {
      key: "failing",
      text: `${capitalise(thing)} have just started failing. Nothing has noticed yet.`,
    };
  }

  return { key: "normal", text: "Payments are running normally. Nothing is wrong yet." };
}
