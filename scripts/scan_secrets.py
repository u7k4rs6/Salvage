#!/usr/bin/env python3
"""Secret scanner used by the pre-commit hook.

docs/03_SECURITY_AND_ACCESS.md section 3 requires a secret scanner before every commit because the
repo is public. This is a self-contained scanner rather than gitleaks or detect-secrets so the hook
works with no network, no extra dependency and no baseline file to keep in sync.

Usage:
  scripts/scan_secrets.py            scan staged content (what the hook does)
  scripts/scan_secrets.py --all      scan every tracked file
Exit code 1 means something matched and the commit is refused.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

# Each rule is (name, compiled pattern). Patterns are deliberately narrow: a false positive that
# blocks a commit is far more annoying than a rule that needs one more line.
RULES: list[tuple[str, re.Pattern[str]]] = [
    ("razorpay live key id", re.compile(r"rzp_live_[A-Za-z0-9]{10,}")),
    # A test key id in a doc or example is fine; a test key id with a real-looking secret is not.
    (
        "razorpay key secret",
        re.compile(r"(?i)razorpay[_-]?key[_-]?secret\s*[:=]\s*['\"]?[A-Za-z0-9]{20,}"),
    ),
    (
        "razorpay webhook secret",
        re.compile(r"(?i)razorpay[_-]?webhook[_-]?secret\s*[:=]\s*['\"]?[A-Za-z0-9]{16,}"),
    ),
    ("google api key", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("aws access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}")),
    ("slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    (
        "generic bearer token assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|auth[_-]?token|access[_-]?token)"
            r"\s*[:=]\s*['\"][A-Za-z0-9_\-]{32,}['\"]"
        ),
    ),
]

# Placeholders that appear in .env.example and the docs on purpose, plus an explicit pragma.
# A line carrying "secret-scan-allow" is skipped. Used by the scanner's own tests, which have to
# contain strings that look exactly like the thing being caught.
ALLOWED = re.compile(
    r"(?i)replace_with|xxxxxxxx|placeholder|your[_-]|example|<[a-z_]+>|secret-scan-allow"
)

SKIP_SUFFIXES = (".lock", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".xlsx", ".ico", ".woff2")


def staged_files() -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in out.stdout.splitlines() if line]


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
    return [line for line in out.stdout.splitlines() if line]


def content_of(path: str, staged: bool) -> str:
    if staged:
        proc = subprocess.run(["git", "show", f":{path}"], capture_output=True, check=False)
    else:
        proc = subprocess.run(["cat", path], capture_output=True, check=False)
    if proc.returncode != 0:
        return ""
    return proc.stdout.decode("utf-8", errors="replace")


def scan(paths: list[str], staged: bool) -> list[str]:
    findings: list[str] = []
    for path in paths:
        if path.endswith(SKIP_SUFFIXES):
            continue
        if path == "scripts/scan_secrets.py":
            continue  # the rules themselves look like secrets
        text = content_of(path, staged)
        if not text:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if ALLOWED.search(line):
                continue
            for name, pattern in RULES:
                if pattern.search(line):
                    findings.append(f"{path}:{lineno}: {name}")
                    break
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan for committed secrets.")
    parser.add_argument("--all", action="store_true", help="scan every tracked file, not the index")
    args = parser.parse_args()

    staged = not args.all
    paths = staged_files() if staged else tracked_files()
    # .env must never be committed even if .gitignore is edited away.
    for path in paths:
        if path == ".env" or path.startswith(".env.") and path != ".env.example":
            print(f"secret scan: refusing to commit {path}", file=sys.stderr)
            return 1

    findings = scan(paths, staged)
    if findings:
        print("secret scan found possible secrets:", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        print("Remove them, or add a placeholder the scanner recognises.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
