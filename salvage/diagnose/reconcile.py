"""Reconciliation: turn a rules verdict and a model verdict into one diagnosis.

docs/02_TECHNICAL_ARCHITECTURE.md section 6:

  If LLM and rules agree, confidence is max(llm.confidence, 0.7). If they disagree, confidence is
  min(llm.confidence, 0.5), which is below the 0.6 action threshold, so the incident escalates
  with both hypotheses in the ticket.

The 0.6 threshold is the policy engine's, in Architecture section 7. It is named here as
ACTION_CONFIDENCE_THRESHOLD so there is one number, not two that can drift apart.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from salvage.diagnose.evidence import EvidencePacket, build_for_incident
from salvage.diagnose.rules import RulesVerdict, classify

# Architecture section 7, policy check 1: an action needs confidence of at least 0.6.
ACTION_CONFIDENCE_THRESHOLD = 0.6

AGREEMENT_FLOOR = 0.7
DISAGREEMENT_CEILING = 0.5


@dataclass(frozen=True)
class Diagnosis:
    """The reconciled result, plus both inputs so the ticket can show the disagreement."""

    incident_id: str
    rules_cause: str
    llm_cause: str | None
    root_cause: str
    confidence: float
    agreed: bool | None
    rationale: str
    rules_detail: str
    escalate: bool
    escalation_reason: str | None

    def to_row(self) -> dict[str, Any]:
        return {
            "rules_cause": self.rules_cause,
            "llm_cause": self.llm_cause,
            "root_cause": self.root_cause,
            "confidence": self.confidence,
        }


def reconcile(
    *,
    incident_id: str,
    rules: RulesVerdict,
    llm_cause: str | None,
    llm_confidence: float | None,
    llm_rationale: str | None,
    llm_failed: bool = False,
    llm_failure_detail: str | None = None,
) -> Diagnosis:
    """The rule from Architecture section 6, and nothing else.

    Three inputs produce three shapes:
      the model answered and agrees with the rules, so confidence is lifted to at least 0.7
      the model answered and disagrees, so confidence is pushed to at most 0.5 and it escalates
      the model could not answer, so the rules stand alone and it escalates
    """
    if llm_failed or llm_cause is None:
        # Architecture section 6: invalid model output is retried once with the validation error
        # appended, then escalates. The retry happens in the provider layer; by the time it
        # reaches here the model has already had its second chance.
        return Diagnosis(
            incident_id=incident_id,
            rules_cause=rules.cause,
            llm_cause=None,
            root_cause=rules.cause,
            # The rules alone do not clear the action threshold. The document gives no confidence
            # for a rules-only diagnosis, so it is set just below the threshold: the rules are
            # good enough to describe the incident to a human and not good enough to act on
            # unsupervised. Recorded in docs/BUILD_LOG.md.
            confidence=DISAGREEMENT_CEILING,
            agreed=None,
            rationale=rules.detail,
            rules_detail=rules.detail,
            escalate=True,
            escalation_reason=llm_failure_detail or "no model diagnosis available",
        )

    confidence = float(llm_confidence if llm_confidence is not None else 0.0)
    if llm_cause == rules.cause:
        final = max(confidence, AGREEMENT_FLOOR)
        return Diagnosis(
            incident_id=incident_id,
            rules_cause=rules.cause,
            llm_cause=llm_cause,
            root_cause=rules.cause,
            confidence=final,
            agreed=True,
            rationale=llm_rationale or rules.detail,
            rules_detail=rules.detail,
            escalate=final < ACTION_CONFIDENCE_THRESHOLD,
            escalation_reason=None if final >= ACTION_CONFIDENCE_THRESHOLD else "low confidence",
        )

    final = min(confidence, DISAGREEMENT_CEILING)
    return Diagnosis(
        incident_id=incident_id,
        # Disagreement means neither is trusted enough to act on. The model's cause is carried as
        # the reconciled one because it saw the evidence the rules cannot express, and the
        # confidence is below the action threshold either way, so nothing customer-facing happens
        # until a human picks. Both hypotheses are in the ticket.
        rules_cause=rules.cause,
        llm_cause=llm_cause,
        root_cause=llm_cause,
        confidence=final,
        agreed=False,
        rationale=llm_rationale or "",
        rules_detail=rules.detail,
        escalate=True,
        escalation_reason=(
            f"rules and model disagree: rules say {rules.cause}, model says {llm_cause}"
        ),
    )


def diagnose_incident(
    conn,
    incident: dict[str, Any],
    *,
    provider: Any | None = None,
    packet: EvidencePacket | None = None,
) -> tuple[Diagnosis, EvidencePacket]:
    """Build the evidence, run the rules, optionally ask the model, reconcile.

    provider is an LLMProvider or None. With None this is the rules-only ablation floor, which is
    the mode the accuracy table in docs/RESULTS.md compares the model against.
    """
    packet = packet or build_for_incident(conn, incident)
    rules = classify(packet)

    llm_cause = llm_confidence = llm_rationale = None
    llm_failed = False
    llm_failure_detail = None
    if provider is not None:
        from salvage.diagnose.llm import diagnose_with_model

        outcome = diagnose_with_model(provider, packet)
        if outcome.ok and outcome.diagnosis is not None:
            llm_cause = outcome.diagnosis.root_cause
            llm_confidence = outcome.diagnosis.confidence
            llm_rationale = outcome.diagnosis.rationale
        else:
            llm_failed = True
            llm_failure_detail = outcome.error

    diagnosis = reconcile(
        incident_id=str(incident["id"]),
        rules=rules,
        llm_cause=llm_cause,
        llm_confidence=llm_confidence,
        llm_rationale=llm_rationale,
        llm_failed=llm_failed,
        llm_failure_detail=llm_failure_detail,
    )
    return diagnosis, packet


def persist_diagnosis(conn, diagnosis: Diagnosis, packet: EvidencePacket, ledger=None) -> None:
    """Write the diagnosis onto the incident and record it in the ledger.

    The ledger entry carries the diagnosis and the packet, both of which are PII-free by
    construction (see salvage/diagnose/evidence.py).
    """
    conn.execute(
        "UPDATE incidents SET rules_cause = ?, llm_cause = ?, root_cause = ?, confidence = ? "
        "WHERE id = ?",
        (
            diagnosis.rules_cause,
            diagnosis.llm_cause,
            diagnosis.root_cause,
            diagnosis.confidence,
            diagnosis.incident_id,
        ),
    )
    if ledger is not None:
        ledger.append(
            "diagnose.reconciled",
            "incident",
            diagnosis.incident_id,
            {
                "rules_cause": diagnosis.rules_cause,
                "llm_cause": diagnosis.llm_cause,
                "root_cause": diagnosis.root_cause,
                "confidence": diagnosis.confidence,
                "agreed": diagnosis.agreed,
                "escalate": diagnosis.escalate,
                "escalation_reason": diagnosis.escalation_reason,
                "rules_detail": diagnosis.rules_detail,
                "rationale": diagnosis.rationale[:600],
                "evidence": json.loads(packet.model_dump_json()),
            },
            ts=packet.window_end,
        )
