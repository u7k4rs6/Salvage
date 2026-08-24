"""Settings loaded from the environment, per docs/03_SECURITY_AND_ACCESS.md section 3.

Every secret comes from an environment variable. Nothing is defaulted to a real value. The one
hard refusal here is the Razorpay key id prefix check: Salvage never runs against live keys.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

TEST_KEY_PREFIX = "rzp_test_"


class ConfigError(RuntimeError):
    """Raised at startup when configuration is unusable. Never caught to keep running."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    gemini_api_key: str = ""

    salvage_dashboard_token: str = ""
    salvage_env: Literal["dev", "demo"] = "dev"
    salvage_kill_switch: bool = False

    salvage_llm_provider: Literal["gemini", "ollama", "fixture"] = "fixture"
    salvage_llm_model: str = "gemini-2.5-flash"

    salvage_db_path: Path = Path("data/salvage.db")
    salvage_ref_hash_salt: str = "salvage-dev-salt"

    # Freshness window for the demo-mode webhook check, in seconds.
    # docs/03_SECURITY_AND_ACCESS.md section 4 fixes this at 15 minutes.
    webhook_freshness_seconds: int = Field(default=900, ge=1)

    @field_validator("razorpay_key_id")
    @classmethod
    def _test_mode_only(cls, value: str) -> str:
        """Refuse anything that is not a test key. An empty value is allowed: the simulator,
        detector and ledger do not touch Razorpay, so M1 runs without credentials. The moment a
        key id is present it must be a test key."""
        if value and not value.startswith(TEST_KEY_PREFIX):
            raise ValueError(
                f"RAZORPAY_KEY_ID must start with {TEST_KEY_PREFIX!r}. "
                "Salvage refuses to run against live Razorpay keys."
            )
        return value

    @property
    def is_dev(self) -> bool:
        return self.salvage_env == "dev"

    def require_razorpay_credentials(self) -> None:
        """Called by code paths that actually talk to Razorpay. M1 has none of those."""
        if not self.razorpay_key_id or not self.razorpay_key_secret:
            raise ConfigError("RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be set")
        if not self.razorpay_key_id.startswith(TEST_KEY_PREFIX):
            raise ConfigError(f"RAZORPAY_KEY_ID must start with {TEST_KEY_PREFIX!r}")

    def require_webhook_secret(self) -> str:
        if not self.razorpay_webhook_secret:
            raise ConfigError("RAZORPAY_WEBHOOK_SECRET must be set to verify webhooks")
        return self.razorpay_webhook_secret

    def secret_values(self) -> list[str]:
        """Values a log redactor must never emit. See section 3 of the security doc."""
        return [
            v
            for v in (
                self.razorpay_key_secret,
                self.razorpay_webhook_secret,
                self.gemini_api_key,
                self.salvage_dashboard_token,
                self.salvage_ref_hash_salt,
            )
            if v
        ]


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings. Cached so the .env file is read once.

    pydantic-settings raises ValidationError on a live key id; we re-raise as ConfigError so the
    CLI and the API report one clear message instead of a validation traceback.
    """
    try:
        return Settings()
    except ValueError as exc:  # ValidationError subclasses ValueError
        raise ConfigError(str(exc)) from exc


def reset_settings_cache() -> None:
    """Tests change the environment between cases and need the cache dropped."""
    get_settings.cache_clear()
