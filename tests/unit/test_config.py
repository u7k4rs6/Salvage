"""Startup configuration rules from docs/03_SECURITY_AND_ACCESS.md section 3."""

from __future__ import annotations

import pytest

from salvage.config import ConfigError, Settings, get_settings, reset_settings_cache


def _settings(**overrides) -> Settings:
    base = {
        "razorpay_key_id": "",
        "razorpay_key_secret": "",
        "razorpay_webhook_secret": "",
        "gemini_api_key": "",
        "salvage_dashboard_token": "t",
        "salvage_ref_hash_salt": "s",
        "_env_file": None,
    }
    base.update(overrides)
    return Settings(**base)


def test_live_key_id_is_refused():
    with pytest.raises(ValueError, match="rzp_test_"):
        _settings(razorpay_key_id="rzp_live_abcdefghij")  # secret-scan-allow


def test_test_key_id_is_accepted():
    assert _settings(razorpay_key_id="rzp_test_abcdefghij").razorpay_key_id.startswith("rzp_test_")


def test_missing_key_id_is_allowed_but_refused_where_it_matters():
    settings = _settings()
    with pytest.raises(ConfigError):
        settings.require_razorpay_credentials()


def test_non_test_key_refused_by_require_even_if_validator_bypassed():
    settings = _settings(razorpay_key_id="rzp_test_abcdefghij", razorpay_key_secret="x")
    settings.require_razorpay_credentials()
    object.__setattr__(settings, "razorpay_key_id", "rzp_live_abcdefghij")  # secret-scan-allow
    with pytest.raises(ConfigError, match="rzp_test_"):
        settings.require_razorpay_credentials()


def test_get_settings_raises_config_error_on_live_key(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_live_abcdefghij")  # secret-scan-allow
    reset_settings_cache()
    try:
        with pytest.raises(ConfigError):
            get_settings()
    finally:
        reset_settings_cache()


def test_secret_values_excludes_empties():
    settings = _settings(razorpay_key_secret="abc", gemini_api_key="")
    assert "abc" in settings.secret_values()
    assert "" not in settings.secret_values()


def test_webhook_secret_required_when_verifying():
    with pytest.raises(ConfigError):
        _settings().require_webhook_secret()
    assert _settings(razorpay_webhook_secret="w").require_webhook_secret() == "w"
