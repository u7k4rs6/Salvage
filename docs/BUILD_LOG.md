# Salvage build log

Dated entries from day one of coding. Each entry records a decision on an open item, a frozen
threshold, or something that broke with what fixed it and what test now guards it. No em dashes or
en dashes anywhere in this repository, by instruction.

---

## 2026-08-24, M1 step 1: repository skeleton

### Decisions on open items

- **Docs location.** The four specs arrived in `files/`. Architecture section 13 puts them in
  `docs/`, so they were moved there unchanged. Reason: the layout in the spec is the spec.
- **CLI framework.** Architecture section 14 lists no CLI library. The minimal CLI uses stdlib
  `argparse` rather than adding typer or click. Reason: no dependency beyond the fixed list, and
  seven subcommands do not need more.
- **Secret scanner.** Section 3 of the security doc allows "gitleaks or the `detect-secrets`
  baseline". Neither is used. `scripts/scan_secrets.py` is a self-contained regex scanner run by
  `.githooks/pre-commit` and by CI. Reason: it needs no network, no extra dependency and no
  baseline file that drifts out of date. It also refuses any commit that includes `.env`.
  Install the hook with `git config core.hooksPath .githooks`.
- **`apscheduler`.** Architecture section 14 says "apscheduler or a hand-rolled asyncio loop
  (decide in M2)". Not added in M1. Reason: nothing in M1 schedules anything; the simulator drives
  its own clock.
- **Empty Razorpay key id is allowed.** The security doc says startup refuses a key id that is not
  a test key. It is refused when present. An absent key id is allowed so the simulator, detector
  and ledger run with no credentials at all, which is what CI does. Any code path that actually
  calls Razorpay goes through `Settings.require_razorpay_credentials()`, which refuses both an
  empty and a non-test key id.
- **Python version pin.** `requires-python = ">=3.12,<3.13"`. Reason: system Python 3.14 is
  externally managed and the project pins a uv-managed 3.12 per Architecture section 14. The upper
  bound stops a stray 3.13 or 3.14 interpreter from resolving.

### What broke

- `uv sync` failed with `OSError: Readme file does not exist: README.md` because `pyproject.toml`
  declared a readme before the file existed. Fixed by writing `README.md` before syncing. No test
  guards this; CI would catch it on the first `uv sync`.
