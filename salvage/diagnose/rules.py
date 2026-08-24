"""Rules classifier.

docs/02_TECHNICAL_ARCHITECTURE.md section 6 gives the table and says it is evaluated in order:

  merchant_config      dominant error_source is business, or merchant_config_changed_recently and
                       reasons are validation or configuration errors
  issuer_outage        segment is a single handle, issuer or bank; dominant source is bank or
                       issuer_bank; sibling segments healthy
  auth_failure_bin     segment is a BIN prefix, issuer or network; dominant step is
                       payment_authentication; siblings healthy
  gateway_degradation  two or more methods degraded; dominant source is gateway or internal;
                       reasons are timeouts or gateway errors
  customer_side        dominant source is customer; no sibling structure (diffuse)
  unknown              none of the above

Deterministic and model-free. This is the ablation floor: docs/01_PRD.md section 12 requires
root-cause accuracy to be reported for rules-only and LLM-assisted separately, and says that if
the model adds nothing the results must say so. That comparison is only meaningful if the floor
exists first and is not quietly improved afterwards to flatter the model.

One ambiguity in the table is worth knowing about before reading the code. A card issuer segment
satisfies the segment test for both issuer_outage ("issuer") and auth_failure_bin ("issuer"). The
table is evaluated in order, so issuer_outage wins, and an authentication failure on a card issuer
is therefore classified as an issuer outage. That is the documented behaviour and it is left
alone; where it costs accuracy, the number is reported rather than the rule bent. See
docs/BUILD_LOG.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from salvage.detect.segments import ALL_KEY, parse_key
from salvage.diagnose.evidence import EvidencePacket
from salvage.taxonomy import RootCause

# Segment dimensions each rule accepts.
INSTRUMENT_DIMENSIONS = frozenset({"upi_handle", "nb_bank", "card_issuer"})
CARD_DIMENSIONS = frozenset({"card_bin6", "card_issuer", "card_network"})

# "dominant source is bank or issuer_bank" (Architecture section 6).
ISSUER_SOURCES = frozenset({"bank", "issuer_bank"})
GATEWAY_SOURCES = frozenset({"gateway", "internal"})

# "reasons are validation or configuration errors". Every value is a published Razorpay reason;
# see salvage/taxonomy.py for the source. These are the reasons that mean the merchant's own
# setup is wrong rather than the customer's instrument or the rail.
CONFIG_REASONS = frozenset(
    {
        "amount_less_than_minimum_amount",
        "bank_not_enabled",
        "card_network_not_enabled",
        "input_validation_failed",
        "international_transaction_not_allowed",
        "invalid_amount",
        "invalid_currency",
        "invalid_order_id",
        "invalid_request",
        "live_mode_not_enabled",
        "merchant_not_activated",
        "order_amount_mismatch",
        "order_payment_method_mismatch",
        "payment_amount_tampered",
        "payment_method_not_enabled",
        "recurring_payment_not_enabled",
        "upi_collect_not_enabled",
        "upi_intent_not_enabled",
    }
)

# "reasons are timeouts or gateway errors".
GATEWAY_REASONS = frozenset(
    {
        "gateway_technical_error",
        "invalid_response_from_gateway",
        "payment_declined_due_to_high_traffic",
        "payment_timed_out",
        "request_timed_out",
        "server_error",
        "payment_session_expired",
        "deemed_transaction",
    }
)

# A share below this is not a dominant value. The table says "dominant" without a number; a plain
# plurality is the weakest reading that still means the word, so the dominant value is the largest
# one and it has to be at least this share of the window's failures.
DOMINANCE_SHARE = 0.40


def _class_share(distribution, members: frozenset[str]) -> float:
    """How much of this window's failures fall in a class of reasons.

    The table says "reasons are validation or configuration errors" and "reasons are timeouts or
    gateway errors", both plural. That is a statement about the reason mix, not about a single
    dominant value, and reading it as the latter was wrong: a gateway outage spreads its failures
    across four gateway reasons, none of which is individually dominant, while together they are
    almost all of the window. See docs/BUILD_LOG.md.
    """
    return sum(share for value, share in distribution.window.items() if value in members)


@dataclass(frozen=True)
class RulesVerdict:
    cause: str
    rule: str
    detail: str

    @property
    def is_known(self) -> bool:
        return self.cause != RootCause.UNKNOWN.value


def _dominant(distribution) -> tuple[str | None, float]:
    value, share = distribution.dominant()
    if value is None or share < DOMINANCE_SHARE:
        return None, share
    return value, share


def _siblings_all_healthy(packet: EvidencePacket) -> bool:
    """No sibling at the same level is degraded.

    An empty sibling map counts as healthy: a segment with no siblings in the window cannot have
    a degraded one, and refusing to classify because a merchant only uses one bank would be worse.
    """
    return all(health == "healthy" for health in packet.sibling_segments.values())


def _degraded_method_count(packet: EvidencePacket) -> int:
    """How many payment methods are degraded at once.

    Two sources, and the larger wins.

    The incident's affected scope is the better one. It is what the detector found firing, decided
    with the frozen thresholds at the moment it decided them, and an incident whose scope names
    three methods is by definition a three-method incident.

    Sibling health is the fallback, and on its own it is not enough. An evidence packet is built
    over the 15-minute window ending at detection, and detection happens a few minutes into a
    fault, so most of that window is from before the fault started and every individual method's
    rate is still diluted below the effect-size threshold even while the merchant-wide key has
    crossed it. Counting only degraded siblings therefore said "zero methods degraded" during a
    gateway outage that had just taken down all four. See docs/BUILD_LOG.md.
    """
    from_scope = len({parse_key(key)[0] for key in packet.affected_scope if key != ALL_KEY})
    from_siblings = sum(1 for health in packet.sibling_segments.values() if health == "degraded")
    return max(from_scope, from_siblings)


def classify(packet: EvidencePacket) -> RulesVerdict:
    """The table, in order. The first rule that matches wins."""
    _, dimension, _ = parse_key(packet.segment_key)
    source, source_share = _dominant(packet.error_source_dist)
    step, step_share = _dominant(packet.error_step_dist)
    reason, reason_share = _dominant(packet.error_reason_dist)
    siblings_healthy = _siblings_all_healthy(packet)

    # 1. merchant_config
    if source == "business":
        return RulesVerdict(
            RootCause.MERCHANT_CONFIG.value,
            "merchant_config.business_source",
            f"dominant error_source is business at {source_share:.2f}",
        )
    config_share = _class_share(packet.error_reason_dist, CONFIG_REASONS)
    if packet.merchant_config_changed_recently and config_share >= DOMINANCE_SHARE:
        return RulesVerdict(
            RootCause.MERCHANT_CONFIG.value,
            "merchant_config.recent_change_with_config_reasons",
            f"config changed recently and {config_share:.2f} of failures are configuration "
            f"or validation errors",
        )

    # 2. issuer_outage
    if dimension in INSTRUMENT_DIMENSIONS and source in ISSUER_SOURCES and siblings_healthy:
        return RulesVerdict(
            RootCause.ISSUER_OUTAGE.value,
            "issuer_outage.single_instrument_bank_source",
            f"segment is a single {dimension}, dominant source {source} at {source_share:.2f}, "
            f"{len(packet.sibling_segments)} sibling(s) all healthy",
        )

    # 3. auth_failure_bin
    if dimension in CARD_DIMENSIONS and step == "payment_authentication" and siblings_healthy:
        return RulesVerdict(
            RootCause.AUTH_FAILURE_BIN.value,
            "auth_failure_bin.card_segment_authentication_step",
            f"segment is a card {dimension}, dominant step payment_authentication at "
            f"{step_share:.2f}, siblings all healthy",
        )

    # 4. gateway_degradation
    gateway_share = _class_share(packet.error_reason_dist, GATEWAY_REASONS)
    degraded_methods = _degraded_method_count(packet)
    if degraded_methods >= 2 and source in GATEWAY_SOURCES and gateway_share >= DOMINANCE_SHARE:
        return RulesVerdict(
            RootCause.GATEWAY_DEGRADATION.value,
            "gateway_degradation.multi_method_gateway_source",
            f"{degraded_methods} methods degraded, dominant source {source} at "
            f"{source_share:.2f}, {gateway_share:.2f} of failures are timeouts or gateway errors",
        )

    # 5. customer_side
    if source == "customer" and not any(
        health == "degraded" for health in packet.sibling_segments.values()
    ):
        return RulesVerdict(
            RootCause.CUSTOMER_SIDE.value,
            "customer_side.diffuse_customer_source",
            f"dominant source is customer at {source_share:.2f} with no degraded siblings",
        )

    # 6. unknown
    return RulesVerdict(
        RootCause.UNKNOWN.value,
        "unknown.no_rule_matched",
        f"no rule matched: source={source} ({source_share:.2f}), step={step} ({step_share:.2f}), "
        f"reason={reason} ({reason_share:.2f}), dimension={dimension}",
    )
