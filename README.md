# Salvage

Salvage is an AI agent for merchants on Razorpay that notices when payments start failing in
clusters, works out why, and wins the money back inside hard limits. It is the Track 03 entry for
the Razorpay AI Buildathon 2026.

The loop: a deterministic detector opens an incident when a payment segment degrades, an
LLM-assisted diagnosis cross-checked by rules names the cause, a policy engine validates every
proposed action against an allowlisted menu, and an append-only hash-chained ledger records all of
it. The agent can create Razorpay Payment Links and set checkout display hints. It cannot do
anything else with money.

## Status

Milestone M1 (foundation) is built: migrations and repository layer, ledger with hash chain and
verify, simulator with scenarios S0 to S4, ingest with webhook signature verification, detector with
calibration, a minimal CLI and a minimal FastAPI app. M2 (diagnosis, policy, executor) is not built
yet.

## Documents

- `docs/01_PRD.md` product requirements, scenarios, metrics, milestones
- `docs/02_TECHNICAL_ARCHITECTURE.md` components, data model, detector, simulator, tooling
- `docs/03_SECURITY_AND_ACCESS.md` threat model, secrets, webhook security, ledger integrity
- `docs/04_FRONTEND_SPEC.md` dashboard specification (M4)
- `docs/BUILD_LOG.md` dated build log: decisions, thresholds, what broke and what fixed it

## Setup

System Python is 3.14 and externally managed, so the project pins a uv-managed 3.12 interpreter and
never uses bare `pip`.

```
uv python install 3.12
uv venv --python 3.12
uv sync --all-extras
cp .env.example .env          # fill RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, RAZORPAY_WEBHOOK_SECRET
```

Startup refuses to run if `RAZORPAY_KEY_ID` does not start with `rzp_test_`. Live keys are never
used in this project.

## Commands

```
uv run salvage db migrate
uv run salvage sim run --scenario S1 --seed 1
uv run salvage detect calibrate --seeds 0..4
uv run salvage ledger verify
uv run salvage ledger export --out data/ledger.jsonl
uv run salvage webhooks record --out data/webhooks
uv run salvage webhooks replay data/webhooks     # SALVAGE_ENV=dev only
uv run salvage serve
uv run python scripts/verify_ledger.py data/ledger.jsonl
uv run pytest -q
uv run ruff check .
```

## Compliance note

Salvage follows the spirit of consent, quiet hours and opt-out. It does not claim TRAI, RBI or PCI
compliance. All customer channels are simulated; no real SMS, email or WhatsApp is ever sent.

## Licence

MIT, see `LICENSE`.
