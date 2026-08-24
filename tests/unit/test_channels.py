"""Simulated channel: templates, slot filling, validator.

Architecture section 8. The validator's job is to reject any message containing a promise, a
discount, urgency language beyond the link expiry, or a missing opt-out line.
"""

from __future__ import annotations

import pytest

from salvage.execute import channels


def _render(**overrides):
    kwargs = {
        "template_id": "recovery_link_v1",
        "locale": "en",
        "order_ref": "order_0001",
        "link_url": "https://rzp.io/i/abc123",
        "expiry_text": "72 hours",
        "alternate_method": None,
    }
    kwargs.update(overrides)
    return channels.render(**kwargs)


def test_the_english_template_renders_and_validates():
    message = _render()
    assert message.validation.ok, message.validation
    assert "order_0001" in message.body
    assert "https://rzp.io/i/abc123" in message.body
    assert "Reply STOP" in message.body


def test_the_hinglish_template_renders_and_validates():
    message = _render(locale="hi_en")
    assert message.validation.ok, message.validation
    assert "STOP reply" in message.body


def test_an_unknown_locale_falls_back_to_english():
    assert _render(locale="ta").body == _render(locale="en").body


def test_the_alternate_method_slot_is_rendered_when_present():
    assert "card" in _render(alternate_method="card").body


def test_no_unfilled_slot_survives_rendering():
    assert "{" not in _render().body


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("We guarantee your order will arrive. Reply STOP to opt out.", "promise"),
        ("Here is a 20% off discount. Reply STOP to opt out.", "discount"),
        ("We will refund you immediately. Reply STOP to opt out.", "discount"),
        ("Hurry, last chance to pay. Reply STOP to opt out.", "urgency"),
        ("Act now or your account will be closed. Reply STOP to opt out.", "urgency"),
        ("Pay now to avoid legal action. Reply STOP to opt out.", "pressure"),
    ],
)
def test_the_validator_rejects_banned_content(text, expected):
    result = channels.validate_message(text)
    assert not result.ok
    assert any(failure.startswith(expected) for failure in result.failures)


def test_the_validator_rejects_a_message_with_no_opt_out_line():
    result = channels.validate_message("Your payment did not go through. Try again.")
    assert not result.ok
    assert any(failure.startswith("opt_out") for failure in result.failures)


def test_the_validator_rejects_an_over_length_message():
    body = "x" * (channels.MAX_MESSAGE_CHARS + 1) + " Reply STOP to opt out."
    result = channels.validate_message(body)
    assert not result.ok
    assert any(failure.startswith("length") for failure in result.failures)


def test_the_validator_rejects_an_unfilled_slot():
    result = channels.validate_message("Pay here: {link_url}. Reply STOP to opt out.")
    assert not result.ok
    assert any(failure.startswith("template") for failure in result.failures)


def test_the_validator_reports_every_failure_not_just_the_first():
    result = channels.validate_message("Hurry, 20% off, guaranteed.")
    assert len(result.failures) >= 3


def test_the_validator_does_not_fire_on_ordinary_wording():
    """A validator that cries wolf gets turned off, and a validator that is off protects nothing."""
    for body in (
        "Your payment for order 12345 did not go through. Reply STOP to opt out.",
        "You can complete it here: https://rzp.io/i/x. Reply STOP to opt out.",
        "This link works until 72 hours. Reply STOP to opt out.",
    ):
        assert channels.validate_message(body).ok, body


def test_a_hostile_slot_cannot_reopen_a_template_placeholder():
    """The model fills slots. It does not get to add structure."""
    message = _render(alternate_method="card{link_url}")
    assert "{" not in message.body
    assert message.validation.ok


def test_control_characters_in_a_slot_are_stripped():
    message = _render(alternate_method="card\x00\x1bnetbanking")
    assert "\x00" not in message.body
    assert "\x1b" not in message.body


def test_a_discount_injected_through_a_slot_is_caught():
    """The validator runs on the rendered message, which is the only reason this is caught."""
    message = _render(alternate_method="a 50% off coupon")
    assert not message.validation.ok
    assert any(failure.startswith("discount") for failure in message.validation.failures)


def test_the_comm_row_stores_a_hash_and_never_the_body():
    message = _render()
    row = channels.comm_row(
        comm_id="comm_1",
        customer_id="cust_1",
        case_id="case_1",
        incident_id="inc_1",
        message=message,
        sent_at=1000,
    )
    assert row["body_hash"] == message.body_hash
    assert len(row["body_hash"]) == 64
    assert message.body not in str(row)
    assert "https://rzp.io" not in str(row)


def test_an_unknown_template_is_an_error_not_a_silent_default():
    with pytest.raises(KeyError):
        channels.render(
            template_id="does_not_exist",
            locale="en",
            order_ref="o",
            link_url="u",
            expiry_text="e",
        )
