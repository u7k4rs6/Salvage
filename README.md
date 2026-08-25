# Salvage

Salvage is an AI agent for merchants on Razorpay that notices when payments start failing in
clusters, works out why, and wins the money back inside hard limits. It is the Track 03 entry for
the Razorpay AI Buildathon 2026.

The merchant it is built for is a large D2C brand: about 12,000 payment attempts a day across
about 8,000 customers. That size is deliberate and it is a constraint, not a boast. A detector
that has to call a single failing UPI handle inside 15 minutes needs enough attempts on that
handle in a 15-minute window to tell a real drop from noise, and a smaller merchant does not
supply them. Traffic volume is a simulator parameter rather than a constant, and the results
include a sweep over it, so the numbers say where this approach stops working instead of pretending
it always does.

The loop: a deterministic detector opens an incident when a payment segment degrades, an
LLM-assisted diagnosis cross-checked by rules names the cause, a policy engine validates every
proposed action against an allowlisted menu, and an append-only hash-chained ledger records all of
it. The agent can create Razorpay Payment Links and set checkout display hints. It cannot do
anything else with money.

## Run the demo

Two processes, both on loopback. Backend first:

```
uv sync --all-extras
cp .env.example .env
uv run salvage db migrate
SALVAGE_DASHBOARD_TOKEN=demo-token uv run salvage serve
```

Then the console, in a second terminal:

```
cd web
npm install
npm run dev
```

Open `http://127.0.0.1:5173`, paste `demo-token` into the token box in the top bar, and go to
Scenario Runner. Pick a scenario, a seed and a policy, and press run. The run resets the database
first, because a scenario is a whole world and two worlds in one database collide on the first
customer they share.

The token lives in React state and is never written to `localStorage`, so a page reload asks for it
again. Read routes are open on loopback; every mutating route requires the bearer token. The API
binds to 127.0.0.1 and CORS is limited to the Vite dev and preview origins.

The whole demo also runs without a browser:

```
uv run salvage agent run --scenario S1 --seed 1 --policy B1
uv run salvage ledger verify
```

## The console

Seven pages, in the build order of `docs/04_FRONTEND_SPEC.md` section 9.

- **Overview** merchant-wide success rate, the segment heatmap with the merchant row pinned at the
  top, open incidents and today's recovery.
- **Incidents** the list, filtered by state.
- **Incident detail** the evidence packet the diagnosis saw, the rules and model verdicts side by
  side, the action timeline, and a ledger slice for that incident alone.
- **Escalations** the queue, with an approve or reject decision that requires a written note.
- **Ledger** browse, verify the chain, and export JSONL that the offline verifier reads.
- **Results** the sweep tables, served from the same JSON that produced `docs/RESULTS.md`.
- **Storefront** a checkout page that shows what a customer sees when the agent sets a display
  hint. It says plainly when it cannot take a real order because no Razorpay key is configured.
- **Scenario Runner** start a run, watch it over server-sent events, and flip the kill switch.

## Status

M1 to M4 are built: migrations and repository layer, hash-chained ledger with an offline verifier
and a commitment to the event stream, simulator with scenarios S0 to S4 and organic customer
retries, webhook ingest with signature verification, detector with frozen calibrated thresholds,
evidence packets, a rules classifier, an LLM provider layer, the allowlisted action menu and policy
engine, the per-order state machine and executor, the simulated channel, three baselines, a fault
injection suite, the evaluation sweep that writes `docs/RESULTS.md`, the dashboard API and the
console above.

Two things are measured and two are not, and `docs/RESULTS.md` says which is which at the top:

- **Measured:** the three baselines against each other over the at-risk order set, the detector's
  operating envelope, the policy engine (zero violations across 200 runs), and 41 fault injections
  all refused.
- **Not measured:** anything involving an LLM. No Gemini key and no local model were ever present
  in the build environment, the self-authored fixtures M2 shipped were deleted rather than reported
  from, and the agent arm therefore runs with no diagnosis model, escalates every incident and
  recovers exactly what B0 recovers. One command with a key fills that in.

## Documents

- `docs/01_PRD.md` product requirements, scenarios, metrics, milestones
- `docs/02_TECHNICAL_ARCHITECTURE.md` components, data model, detector, simulator, tooling
- `docs/03_SECURITY_AND_ACCESS.md` threat model, secrets, webhook security, ledger integrity
- `docs/04_FRONTEND_SPEC.md` dashboard specification
- `docs/RESULTS.md` the sweep, with the two limitations stated before the first table
- `docs/results_by_run.csv` one row per run, so any table above can be recomputed
- `docs/WHAT_BROKE.md` the defects worth reading about, measurement bugs first
- `docs/PITCH.md` the three-minute version
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
uv run salvage sim run --scenario S1 --seed 1 --variant offpeak
uv run salvage sim verify-stream
uv run salvage sim organic --seeds 0..4
uv run salvage detect calibrate --seeds 5..9
uv run salvage diagnose accuracy --seeds 0..9 --provider none
uv run salvage eval run --scenarios S0,S1,S2,S3,S4 --seeds 0..9 --policies agent,B0,B1,B2
uv run salvage eval volume --scenarios S1,S2 --seeds 0..4
uv run salvage eval sensitivity --seeds 0..4 --adversarial
uv run salvage eval report
uv run salvage e2e verify
uv run salvage agent run --scenario S1 --seed 1 --policy B1
uv run salvage agent run --scenario S1 --seed 1 --policy B1 --kill-switch
uv run salvage demo reset
uv run salvage demo kill-switch on
uv run salvage ledger verify
uv run salvage ledger export --out data/ledger.jsonl
uv run salvage webhooks record --out data/webhooks
uv run salvage webhooks replay data/webhooks     # SALVAGE_ENV=dev only
uv run salvage serve
uv run python scripts/verify_ledger.py data/ledger.jsonl
uv run pytest -q
uv run ruff check .
```

`salvage demo reset` empties every table and prints the database path before it does. It takes the
global `--db` flag like every other command.

## The kill switch

`SALVAGE_KILL_SWITCH=1`, or the switch in the console top bar, suspends every outbound action. It
is checked in the policy engine, so a suspended agent still detects, still diagnoses and still
files escalations; it just stops calling out. On S1 seed 1 under B1 the same world produces 1,038
messages with the switch off and zero with it on, and recovery falls to what customers manage on
their own. `docs/BUILD_LOG.md` has the rehearsal, including the two defects the rehearsal found in
the wiring around the switch.

## A note on the LLM fixtures

`salvage/llm/fixtures/` is empty. M2 shipped 46 fixtures written by the model being evaluated,
with the scenario labels visible to its author; they were deleted in M3 and no number was ever
taken from them. Refilling the directory blind is one command, and the isolation is enforced by
the code path rather than by discipline:

```
export GEMINI_API_KEY=...
uv run salvage diagnose record-fixtures --scenarios S1,S2,S3,S4 --seeds 0..9 --provider gemini
```

`salvage/llm/fixtures/README.md` explains what went wrong and what the recorder does about it.

## Compliance note

Salvage follows the spirit of consent, quiet hours and opt-out. It does not claim TRAI, RBI or PCI
compliance. All customer channels are simulated; no real SMS, email or WhatsApp is ever sent.

## Licence

MIT, see `LICENSE`.
