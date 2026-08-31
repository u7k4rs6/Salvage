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

Open `http://127.0.0.1:5173` and paste `demo-token` into the token box in the top bar. That token
is needed only for the routes that change something: the kill switch, and approving or rejecting an
escalation. Everything else reads.

Scenario Runner needs neither the token nor the backend. It replays a recording committed to
`web/src/board/fixtures/`, because `POST /api/sim/run` simulates, detects, diagnoses, acts and
settles in one uninterruptible call and there is nothing to watch while it does. To run a scenario
for real, use the CLI below and then read the result on the other pages.

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
- **Scenario Runner** a recorded run, replayed from its own ledger at a speed you choose.
  `POST /api/sim/run` simulates, detects, diagnoses, acts and settles in one uninterruptible call,
  so there is no moment at which the running system holds a partial world and nothing to watch
  while it works. The page replays a recording committed to `web/src/board/fixtures/` instead.
  Every frame is recorded data: the position of the playhead is the only state, every panel is a
  function of it, and where the run did not record something the page shows nothing rather than a
  guess.

## The public demo

Two of those pages need no backend: the Scenario Runner reads a committed recording, and Results
reads a committed artifact. Those two are what a production build ships. The other five all read a
live FastAPI process, and five error panels are a worse first impression than five absent pages, so
a production build leaves them out. There is nothing to configure at deploy time and no environment
variable the deployed page reads.

```
cd web
npm ci
npm run build          # writes web/dist, including 404.html for hosts without a rewrite rule
npx vite preview       # serves it on 127.0.0.1:4173 with the rewrite in place
```

Deploying to Vercel, from the repository root. `web/vercel.json` carries the build command, the
output directory and the rewrite that makes a deep link like `/runner` work on a hard refresh:

```
npx vercel --cwd web            # preview deployment, prints the URL
npx vercel --prod --cwd web     # production
```

Deploying to Vercel from the dashboard instead, by connecting the repository. One setting matters
and it is not the default: **Root Directory must be `web`**, because that is where `package.json`
and `vercel.json` live. Point Vercel at the repository root and the build fails with no
`package.json` found. Everything else Vercel infers correctly from `web/vercel.json`:

| Setting | Value | Where it comes from |
| --- | --- | --- |
| Root Directory | `web` | set this by hand |
| Framework preset | Vite | detected |
| Build command | `npm run build` | `web/vercel.json` |
| Output directory | `dist` | `web/vercel.json` |
| Install command | `npm ci` | the committed lockfile |
| Environment variables | none | a production build reads none |

Leave the environment variables empty. Setting `VITE_SALVAGE_FULL=1` there would ship the five
pages that need a backend, and on Vercel there is no backend for them to reach.

Deploying to GitHub Pages. Pages has no rewrite rule, so the build copies `index.html` to
`404.html` and Pages serves that for any unknown path, which does the same job. A project site
lives under a repository subpath, so the build needs to know it:

```
cd web
VITE_BASE=/salvage/ npm run build
npx gh-pages -d dist
```

To build the full console instead, for a deployment that will sit in front of a running backend:

```
VITE_SALVAGE_FULL=1 npm run build
```

Bundle, measured on the last build: 30 kB of JavaScript and 8 kB of CSS, both gzipped, before any
recording is fetched. The two recordings are static assets rather than bundled modules, so the
1.5 MB one (129 kB gzipped) is fetched when the Scenario Runner opens and the other only if you
switch to it. Recharts is 151 kB gzipped and is split into its own chunk that only Results pulls
in, so a visitor who never opens Results never downloads it.

## Status

M1 to M5 are built: migrations and repository layer, hash-chained ledger with an offline verifier
and a commitment to the event stream, simulator with scenarios S0 to S4 and organic customer
retries, webhook ingest with signature verification, detector with frozen calibrated thresholds,
evidence packets, a rules classifier, an LLM provider layer, the allowlisted action menu and policy
engine, the per-order state machine and executor, the simulated channel, three baselines, a fault
injection suite, the evaluation sweep that writes `docs/RESULTS.md`, the dashboard API, the console
above, and the escalation-to-fix sweep.

**The agent arm is measured.** Its diagnosis fixtures were recorded blind from Gemini: the recorder
builds each evidence packet through the same call the agent makes, which cannot reach the
ground-truth tables, hands the model a type carrying the prompt and its hash and nothing else, and
refuses any prompt in which a scenario id, a seed or a cause name appears. `docs/RESULTS.md` reads
its provenance line out of the fixture files rather than asserting it.

Recovered revenue in rupees over the at-risk order set against messages sent, mean of 10 seeds:

| scenario | agent | B0 | B1 | B2 |
|---|---|---|---|---|
| S1 issuer outage | **2,21,154 / 83 msg** | 93,947 / 0 msg | 1,47,797 / 164 msg | 1,75,050 / 261 msg |
| S2 BIN auth failure | **1,20,065 / 44 msg** | 50,095 / 0 msg | 79,263 / 88 msg | 93,255 / 140 msg |
| S3 gateway degradation | **4,78,668 / 422 msg** | 3,01,760 / 0 msg | 4,20,743 / 312 msg | 4,72,828 / 492 msg |
| S4 merchant misconfiguration | 90,128 / 0 msg | 90,128 / 0 msg | 1,57,696 / 178 msg | 1,65,041 / 272 msg |

The agent wins S1 by 26 percent on 32 percent of B2's messages, and S2 by 29 percent on 31 percent
of its messages. **S3 is a tie, not a win:** 5,840 rupees on a paired standard deviation of 15,993
across ten seeds, with the agent losing 1 of the 10 seeds outright, and 86 percent of B2's message count
rather than a third. **It loses S4 outright**, and that row is the one worth reading: the cause is
a merchant misconfiguration, so it contacts nobody and escalates, recovering exactly what doing
nothing recovers while both baselines message around two hundred customers about something none of
them can fix.

**Scoped to the whole day rather than to the at-risk set, the baselines beat the agent on every
scenario by 29 to 44 percent** (section 2 of the results). They win by messaging a thousand
customers a day, most of whose failures have nothing to do with an incident. Both readings are
true; which one matters depends on what a message costs, and this simulator charges almost nothing
for one.

That is restraint measured against no benefit, because an escalation used to reach a human and
change nothing in the world. `escalation_fix_minutes` now models the repair as a swept parameter,
and `docs/RESULTS.md` section 11 reports the curve rather than picking a value off it: at every
response time from 15 minutes to two hours the agent lands between 2,67,435 and 2,77,080 rupees
against B2's 1,83,115, sending nothing. Past the fault's own 180 minute duration a fix is worth
exactly nothing, because the world has already recovered on its own. Only an arm that escalates can
be repaired, which is an asymmetry the results state plainly rather than assume in the agent's
favour.

Diagnosis accuracy over 41 incidents: rules-only 0.902, model 0.976, reconciled 0.976. **On this
workload the language model did not detectably contribute to recovery.** The `echo` arm is the
agent with its model replaced by a stub repeating the rules verdict, everything else identical;
paired across ten seeds it recovers 16,066 rupees more on S1, 6,081 less on S2, 15,266 less on S3
and the same on S4. The signs disagree, no scenario clears a paired t, and the four sum to roughly
minus five thousand rupees. The residual is a confound rather than a result: the reconciled cause
is identical in the 37 of 41 incidents the rules get right, and what differs is the confidence
number in the planner's prompt, 0.70 against 0.95. Two honest reasons it could differ elsewhere:
the rules classifier was written against these exact scenarios, and 41 incidents cannot resolve a
small effect. The gate still earns its place in one direction: a model returning a confident wrong
cause recovers exactly what doing nothing recovers.

The steer conversion probability, the constant the S1 and S2 margins mostly rest on, is swept from
0.25 to 0.65 in section 9. The win survives the whole range and narrows by about three quarters at
the bottom of it.

**Two of the five scenarios key on payload fields that may not be present in production Razorpay
payloads.** S2 detects on `card_bin6` and S1 on `upi_handle`, and those are the primary segment
keys for those scenarios. Razorpay's documented payment entity carries no `iin` on the card object,
only a `token_iin` that is null in the published sample and names a network token rather than the
card, so `card_bin` is None from a documented payload. The webhook docs publish no payment.failed
sample for UPI at all and warn twice that `vpa` may be absent on a UPI failure, which is exactly
the event S1 depends on.

This affects no number above: the simulator emits both fields, the detector reads them, and every
arm faces the same payloads. What it means is that the segment keys would have to be re-derived
against real traffic before this ran in production, and that work has not been done. The fallback
would be the coarser keys the payload does carry, card network, card issuer and the method itself,
which enlarge the denominator and dilute the excess across healthy siblings, so by the operating
envelope it means later detection or none. It is not solved.

Zero policy violations across all 250 runs, and 45 fault injection attempts all refused.

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
