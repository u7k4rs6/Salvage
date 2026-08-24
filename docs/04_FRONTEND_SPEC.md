# Salvage: Frontend Specification

Version 0.1, 24 August 2026. Companion to `02_TECHNICAL_ARCHITECTURE.md`. The frontend exists to make the agent's behaviour legible in a 5-minute pitch and a panel interview. It is an ops console, not a product marketing surface.

## 1. Stack and constraints

- Vite, React 18, TypeScript, Tailwind. React Router for pages. No state library; server state via a small `useApi` hook with SWR-style refetch and an SSE subscription for live updates.
- Charts: a single lightweight library (Recharts) for the results page and the success-rate sparklines; the heatmap is plain divs with Tailwind classes, no charting dependency.
- No component library. A handful of local primitives: `Table`, `Badge`, `Panel`, `Stat`, `Timeline`, `ConfirmButton`, `TokenGate`.
- Runs at `127.0.0.1:5173`, proxies `/api` to the FastAPI server. Memory budget under 400 MB during development.
- Razorpay `checkout.js` is loaded only on the Storefront page, from Razorpay's domain.

## 2. Information architecture

Left rail navigation, seven entries in this order: Overview, Incidents, Escalations, Ledger, Results, Storefront, Scenario Runner. A persistent top bar shows: environment badge (`dev` or `demo`), sim clock (or wall clock when live), active incident count, kill-switch state, and a token entry control.

Every page loads in under one second from a warm SQLite database. Every list is paginated server-side at 50 rows.

## 3. Global elements

- Top bar kill switch: a red toggle that calls `POST /api/control/kill-switch` (token required). When on, the whole top bar carries a red border and the text "Outbound actions suspended".
- Token gate: mutating controls render disabled with a lock icon until a token is entered; the token lives in React state only.
- SSE stream at `GET /api/stream`: events `attempt`, `incident.opened`, `incident.updated`, `incident.closed`, `action.executed`, `action.refused`, `escalation.opened`, `escalation.decided`, `ledger.appended`, `sim.tick`, `sim.finished`. Pages subscribe to what they need and refetch on relevant events.
- Empty, loading and error states are mandatory on every data region: a skeleton row set while loading, a one-line explanation when empty, and an inline error panel with the request id when a call fails.

## 4. Pages

### 4.1 Overview

Purpose: show, at a glance, whether payments are healthy and where they are breaking.

Components:

- Success-rate heatmap: rows are methods (UPI, Card, Netbanking, Wallet), columns are instruments within the method (UPI handles, card issuers, banks). Each cell shows the current 15-minute success rate, coloured on a neutral-to-red scale, with the baseline rate as small text. Cells inside an open incident get a red outline and link to the incident.
- Active incidents strip: one card per open incident with segment, root cause, confidence, at-risk amount, recovered so far, and status badge.
- Volume and failures sparkline for the last 24 sim hours.
- Four stats: attempts in the last hour, current merchant-wide success rate, at-risk revenue (open incidents), recovered today.

Contracts: `GET /api/overview` returns `{ segments: [{key, method, instrument, attempts, failures, rate, baseline, incident_id}], incidents: [...], series: [{t, attempts, failures}], stats: {...} }`.

States: loading skeleton for the heatmap; empty shows "No attempts yet. Run a scenario." with a link to Scenario Runner.

### 4.2 Incidents (list and detail)

List: table with opened time, segment, root cause, confidence, status, at-risk, recovered, actions count, escalation flag. Filter by status. Row click opens detail.

Detail, in this order top to bottom, because it mirrors the loop and the pitch:

1. Header: segment, status badge, opened and closed times, at-risk and recovered amounts, buttons Close (token) and Export ledger slice.
2. Evidence panel: the evidence packet rendered as two side-by-side distributions (window versus baseline) for source, step and reason; sibling segment health as small badges; the five sample descriptions in a monospace block labelled "untrusted text, shown as data".
3. Diagnosis panel: rules cause, LLM cause, reconciled cause, confidence bar with the 0.6 threshold marked, the model's rationale as plain text, and a "Show prompt and raw response" disclosure that reveals the exact text sent and received.
4. Plan panel: the planner's proposed actions with scope, and the policy result per action. Refused actions are shown struck through with the failing rule named.
5. Cases table: one row per recovery case: customer `ref_hash` (short), order id, amount, state, nudges, link id, next action time, outcome. State cell uses the state machine names verbatim.
6. Timeline: the incident's ledger entries in order, each with kind, time, a one-line summary and a disclosure for the full payload. Gate evaluations render as a compact list of rule names with pass or fail marks.

Contracts: `GET /api/incidents?status=`, `GET /api/incidents/{id}` returning `{incident, evidence, diagnosis: {rules, llm, reconciled, prompt, raw_response}, plan: [{action, scope, params, gate: [{rule, passed, detail}]}], cases: [...], timeline: [...]}`, `POST /api/incidents/{id}/close`.

### 4.3 Escalations

Purpose: the human-in-the-loop surface. This page is what "compliant escalation" looks like.

Components: a queue of pending escalations, newest first. Each card shows the incident link, the reason (merchant-side cause, low confidence, matrix refusal, circuit breaker), the evidence summary, the proposed action if any, and two buttons: Approve and Reject, each opening a confirmation with a required one-line note. Decided escalations move to a collapsed history list with the decision, note and time.

Contracts: `GET /api/escalations?status=pending|decided`, `POST /api/escalations/{id}/decision` with `{decision: approve|reject, note}` (token required). The SSE event `escalation.opened` prepends a card with a brief highlight.

States: empty shows "Nothing waiting on you." Error on decision shows the server message inline without losing the note.

### 4.4 Ledger

Purpose: prove the audit trail is real.

Components:

- Verify button: calls `POST /api/ledger/verify` and shows either "Chain intact, N entries, head hash <short>" or "Broken at sequence N" in a persistent banner.
- Filter bar: kind, ref type, incident id, time range.
- Entries table: seq, time, kind, ref, summary, short hash, with a disclosure per row for the full payload and the previous hash.
- Export button: downloads JSONL from `GET /api/ledger/export?from=&to=`.
- A one-paragraph note under the title stating what the chain proves (no post-hoc edits) and what it does not (that the process wrote the truth).

Contracts: `GET /api/ledger?kind=&ref_type=&ref_id=&from=&limit=&cursor=`, `POST /api/ledger/verify`, `GET /api/ledger/export`.

### 4.5 Results

Purpose: the first minute of the pitch.

Components:

- Run selector: pick a results run id; default is the latest.
- Headline table: rows are scenarios, column groups are policies (agent, B0, B1, B2), cells show recovered revenue mean and standard deviation, with the best policy per row emphasised. A second table shows recovery rate, contact efficiency, time to detect, root-cause accuracy, escalation precision, policy violations and false alarms.
- Diagnosis ablation: rules-only versus LLM-assisted accuracy per scenario.
- Sensitivity panel: a small chart of agent-minus-B1 recovered revenue across the multiplier sweep, with the adversarial set marked and labelled plainly ("agent has no advantage here, by design").
- Real end-to-end run panel: the real order id, link id, payment id, webhook event id and the ledger sequence numbers, with a link to each ledger entry.

Contracts: `GET /api/results`, `GET /api/results/{run_id}` returning the same structure the runner writes to `results.json`.

States: empty shows "No evaluation runs yet" with the command to run one.

### 4.6 Storefront

Purpose: show a real Razorpay checkout and make method steering visible.

Components:

- A tiny demo shop: three SKUs with Buy buttons. Buy calls `POST /api/storefront/order` which creates a real test-mode Order and returns the checkout options.
- Checkout opens with Razorpay `checkout.js` using those options. When a `STEER_METHOD` hint is active for the demo customer's segment, the options include the `config.display` block from `GET /api/storefront/checkout-config`, and a banner above the shop says which method is being de-prioritised and why, linking to the incident.
- After payment, the page shows the payment id and waits for the `payment.captured` or `payment.failed` webhook via SSE, then shows the ledger entry it produced.
- A "Simulate my payment failing" control (dev only) that posts a synthetic `payment.failed` for the demo customer so the Overview reacts without a real failed payment.

Contracts: `POST /api/storefront/order` with `{sku}` returning `{order_id, amount, currency, key_id, checkout_config}`, `GET /api/storefront/checkout-config`, `POST /api/storefront/simulate-failure` (dev, token).

### 4.7 Scenario Runner

Purpose: drive the simulator from the UI during the pitch.

Components:

- Form: scenario (S0 to S5), seed, policy (agent, B0, B1, B2), speed (as fast as possible, or paced at N sim minutes per real second for demos).
- Run and Stop buttons (token). Progress: sim clock, attempts processed, incidents opened, actions executed, actions refused, escalations.
- Live log: the last 50 SSE events as one-line entries.
- After finishing: a summary card with the metrics for that run and a link to the incident(s).

Contracts: `POST /api/sim/run`, `POST /api/sim/stop`, `GET /api/sim/status`.

States: only one run at a time; the form disables while a run is active and says so.

## 5. Data contracts summary

| Route | Method | Auth | Used by |
|-------|--------|------|---------|
| `/api/overview` | GET | none | Overview |
| `/api/incidents`, `/api/incidents/{id}` | GET | none | Incidents |
| `/api/incidents/{id}/close` | POST | token | Incident detail |
| `/api/escalations`, `/api/escalations/{id}/decision` | GET, POST | none, token | Escalations |
| `/api/ledger`, `/api/ledger/verify`, `/api/ledger/export` | GET, POST, GET | none | Ledger |
| `/api/results`, `/api/results/{run_id}` | GET | none | Results |
| `/api/storefront/order`, `/api/storefront/checkout-config`, `/api/storefront/simulate-failure` | POST, GET, POST | none, none, token | Storefront |
| `/api/sim/run`, `/api/sim/stop`, `/api/sim/status` | POST, POST, GET | token, token, none | Scenario Runner |
| `/api/control/kill-switch` | POST | token | Top bar |
| `/api/stream` | GET (SSE) | none | all |

All amounts arrive in paise and are formatted client-side as rupees with two decimals and Indian digit grouping. All times arrive as Unix seconds plus a `clock` field (`sim` or `wall`) and are formatted in IST.

## 6. Design direction

Utilitarian ops console. The interface should feel like a good incident tool: dense, calm, fast to scan, never decorative.

- Typography: system UI stack for text; a monospace stack (`ui-monospace, SFMono-Regular, Menlo, Consolas`) for every number, id, hash and code. Numbers right-aligned in tables with tabular figures.
- Colour: neutral greys for structure; one accent (deep teal) for interactive elements and links; red reserved for active incidents, refused actions and the kill switch; amber for pending escalations and deferred cases; green for recovered outcomes and an intact ledger. Nothing else is coloured.
- Layout: full-width tables, 12-column grid on Overview, single column elsewhere. No modals except the two confirmations (escalation decision, kill switch). Disclosures instead of popovers for payloads.
- Density: 13px table text, 32px row height, generous column spacing. Panels have a 1px border and no shadow.
- Motion: none beyond a 150 ms highlight when an SSE event inserts a row.
- Copy: short, declarative, no exclamation marks. Error messages name the failing rule or the request id.

## 7. Accessibility basics

- Every interactive element is reachable and operable by keyboard; Approve, Reject and the kill switch have visible focus rings.
- Tables use real `table` semantics with header scope; the heatmap cells carry `aria-label` with the segment and rate.
- Colour is never the only signal: incident cells also get an outline, refused actions are struck through and labelled, ledger status has text.
- Contrast meets 4.5:1 for text on all backgrounds.

## 8. Out of scope

- Authentication beyond the bearer token, user management, mobile layouts.
- Editing simulator parameters from the UI (they are a YAML file by design).
- Any customer-facing UI beyond the demo storefront.
- Dark mode, theming, internationalisation of the console (messages to customers are bilingual; the console is English).

## 9. Build order (M4, with the Overview and Incident detail pulled forward into M2 for debugging)

1. Primitives, top bar, SSE hook, token gate.
2. Overview heatmap and incidents strip.
3. Incident detail (evidence, diagnosis, plan, cases, timeline).
4. Escalations.
5. Ledger with verify.
6. Scenario Runner.
7. Results.
8. Storefront with real checkout.

Pages 2 and 3 are needed during M2 to see what the agent is doing; the rest can wait for M4.
