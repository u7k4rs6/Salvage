"""The pre-commit secret scanner must actually catch things."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "scan_secrets", Path(__file__).resolve().parents[2] / "scripts" / "scan_secrets.py"
)
assert _spec and _spec.loader
scan_secrets = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_secrets)


def _hits(line: str) -> bool:
    if scan_secrets.ALLOWED.search(line):
        return False
    return any(pattern.search(line) for _, pattern in scan_secrets.RULES)


def test_catches_live_key_id():
    assert _hits("RAZORPAY_KEY_ID=rzp_live_9WxYzAbCdEfGhI")  # secret-scan-allow


def test_catches_google_api_key():
    assert _hits("GEMINI_API_KEY=AIza" + "b" * 35)


def test_catches_private_key_header():
    assert _hits("-----BEGIN PRIVATE KEY-----")  # secret-scan-allow


def test_ignores_env_example_placeholders():
    assert not _hits("RAZORPAY_KEY_SECRET=replace_with_test_key_secret")
    assert not _hits("RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxxxx")


def test_repo_itself_is_clean():
    findings = scan_secrets.scan(scan_secrets.tracked_files(), staged=False)
    assert findings == []
