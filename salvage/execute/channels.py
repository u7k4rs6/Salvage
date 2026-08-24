"""Simulated channel: templates, slot filling, validation.

docs/02_TECHNICAL_ARCHITECTURE.md section 8:

  renders a template (en or hi_en) with slots filled by the LLM planner's optional message_slots
  output, runs the validator (no promise, no discount, no urgency beyond the expiry, opt-out line
  present, length cap), records the message hash in customer_comms, and, in simulation, hands the
  message to the response model. No real SMS, email or WhatsApp is ever sent.

docs/01_PRD.md section 4 puts real channels out of scope explicitly. Nothing in this module opens
a socket. The message body is never stored either: `customer_comms` holds a hash, because the body
contains an order reference and is addressed to a person (docs/03_SECURITY_AND_ACCESS.md
section 5).

The model fills slots. It does not write messages. Rendering happens here, after the model has
returned, from a template that is in the repository and reviewable.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

# Templates. English and Hinglish, as docs/01_PRD.md section 8 requires. The opt-out line is part
# of the template rather than something the validator hopes to find, so it cannot go missing
# unless somebody edits a template, at which point the validator catches it.
TEMPLATES: dict[str, dict[str, str]] = {
    "recovery_link_v1": {
        "en": (
            "Your payment for order {order_ref} did not go through. "
            "You can complete it here: {link_url}. {alternate_line}"
            "This link works until {expiry_text}. "
            "Reply STOP to stop receiving these messages."
        ),
        "hi_en": (
            "Aapka order {order_ref} ka payment complete nahi hua. "
            "Aap yahan se payment kar sakte hain: {link_url}. {alternate_line}"
            "Yeh link {expiry_text} tak valid hai. "
            "Messages band karne ke liye STOP reply karein."
        ),
    },
}

OPT_OUT_MARKERS = ("Reply STOP", "STOP reply")
MAX_MESSAGE_CHARS = 480

# The validator's job, from Architecture section 8: reject any message containing a promise, a
# discount, urgency language beyond the link expiry, or a missing opt-out line.
#
# Each pattern is deliberately narrow. A validator that fires on ordinary words would be turned
# off within a week, and a validator that is off protects nothing.
BANNED_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "promise",
        re.compile(
            r"\b(guarantee|guaranteed|we promise|promise you|assured|assure you|"
            r"will definitely|100% (?:safe|sure|success))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "discount",
        re.compile(
            r"\b(discount|coupon|cashback|off your order|% off|free delivery|refund|waive[dr]?|"
            r"voucher|credit note|reduced price|special price|offer price)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "urgency",
        re.compile(
            r"\b(hurry|hurry up|act now|last chance|final notice|urgent(?:ly)?|immediately|"
            r"right now|don'?t miss|limited time|expires in minutes|only \d+ left)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "pressure",
        re.compile(r"\b(your account will be|you will lose|penalty|legal action)\b", re.IGNORECASE),
    ),
)


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    failures: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return "valid" if self.ok else "; ".join(self.failures)


def validate_message(body: str) -> ValidationResult:
    """The template validator. Returns every failure, not just the first."""
    failures: list[str] = []
    for name, pattern in BANNED_PATTERNS:
        match = pattern.search(body)
        if match:
            failures.append(f"{name}: contains {match.group(0)!r}")
    if not any(marker.lower() in body.lower() for marker in OPT_OUT_MARKERS):
        failures.append("opt_out: the message has no opt-out line")
    if len(body) > MAX_MESSAGE_CHARS:
        failures.append(f"length: {len(body)} characters, cap {MAX_MESSAGE_CHARS}")
    if "{" in body or "}" in body:
        failures.append("template: an unfilled slot remains in the rendered message")
    return ValidationResult(ok=not failures, failures=failures)


def _sanitise_slot(value: str | None, limit: int) -> str:
    """One model-supplied slot, made safe to render.

    Control characters and braces are stripped, because a slot containing a brace could reopen a
    template placeholder, and the whole point of rendering locally is that the model contributes
    words rather than structure.
    """
    if not value:
        return ""
    cleaned = re.sub(r"[\x00-\x1f\x7f{}]", " ", str(value))
    return " ".join(cleaned.split())[:limit]


@dataclass(frozen=True)
class RenderedMessage:
    template_id: str
    locale: str
    body: str
    validation: ValidationResult

    @property
    def body_hash(self) -> str:
        """What goes in customer_comms. The body itself is never stored."""
        return hashlib.sha256(self.body.encode("utf-8")).hexdigest()


def render(
    *,
    template_id: str,
    locale: str,
    order_ref: str,
    link_url: str,
    expiry_text: str,
    alternate_method: str | None = None,
) -> RenderedMessage:
    """Render, then validate. Never the other way round.

    A caller that validated the template rather than the rendered message would miss exactly the
    case the validator exists for: a slot the model filled with something it should not have.
    """
    templates = TEMPLATES.get(template_id)
    if templates is None:
        raise KeyError(f"unknown template {template_id!r}")
    template = templates.get(locale) or templates["en"]

    alternate = _sanitise_slot(alternate_method, 40)
    alternate_line = f"You could also try {alternate}. " if alternate else ""
    if locale == "hi_en" and alternate:
        alternate_line = f"Aap {alternate} bhi try kar sakte hain. "

    body = template.format(
        order_ref=_sanitise_slot(order_ref, 40),
        link_url=_sanitise_slot(link_url, 120),
        expiry_text=_sanitise_slot(expiry_text, 40),
        alternate_line=alternate_line,
    )
    return RenderedMessage(
        template_id=template_id,
        locale=locale,
        body=body,
        validation=validate_message(body),
    )


def comm_row(
    *,
    comm_id: str,
    customer_id: str,
    case_id: str | None,
    incident_id: str | None,
    message: RenderedMessage,
    sent_at: int,
    channel: str = "simulated",
) -> dict[str, Any]:
    """The customer_comms row. Hash only, never the body."""
    return {
        "id": comm_id,
        "customer_id": customer_id,
        "case_id": case_id,
        "incident_id": incident_id,
        "channel": channel,
        "template_id": message.template_id,
        "locale": message.locale,
        "body_hash": message.body_hash,
        "sent_at": sent_at,
    }
