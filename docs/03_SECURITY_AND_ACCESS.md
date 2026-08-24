# Salvage: Security and Access

Version 0.1, 24 August 2026. Companion to `02_TECHNICAL_ARCHITECTURE.md`.

## 1. Scope

Salvage runs on one developer laptop, against one Razorpay test-mode account, with one human operator, for a buildathon demo. That narrows the threat model, and this document is sized to that reality. It still takes three things seriously, because the panel will: the agent must not be able to move money outside its bounds, customer data must not leak into a third-party model, and the audit trail must be trustworthy.

Assets, in priority order:

1. Bounded money actions. The agent can create Payment Links and checkout hints and nothing else.
2. Razorpay credentials (test key pair, webhook secret) and the Gemini API key.
3. Customer data in the database (contacts, emails, order history), synthetic in the demo but treated as real.
4. Ledger integrity.
5. The dashboard as a control surface (approve escalations, run scenarios, kill switch).

## 2. Threat model

| Threat | Vector | Control | Section |
|--------|--------|---------|---------|
| Agent takes an out-of-bounds money action | LLM proposes refund, discount, changed amount, unlisted action | Allowlisted action menu with schemas that cannot express an amount; policy engine validates every action; matrix refusal escalates | 6 |
| Agent spams or contacts customers who did not consent | Bug, model over-eagerness, replayed events | Consent, opt-out, caps, quiet hours enforced in code before every send; property tests | 6 |
| Forged or replayed webhook | Attacker posts to the webhook endpoint | HMAC verification with constant-time compare, event id dedupe, dev-only replay path | 4 |
| Prompt injection through data | Malicious text in `error_description`, order notes, customer names reaches the model | Untrusted fields excluded from prompts or fenced; model output cannot invoke tools; schema validation; fault-injection tests | 7 |
| Customer PII sent to a third-party model | Evidence packet or message slots carry contacts or names | Evidence packet schema has no PII fields; redaction test; message templates are rendered locally after the model returns slots | 5 |
| Credential leak | `.env` committed, keys in logs, keys in the ledger | `.gitignore`, secret scanning pre-commit hook, redaction in logging, ledger stores request ids not headers | 3 |
| Ledger tampering | Direct database edit | Hash chain with `verify` command, JSONL export, append-only writer (no UPDATE or DELETE path in code) | 8 |
| Runaway execution during a bug | Loop creates links repeatedly, retries storm | Idempotent `reference_id`, per-order single open link, circuit breaker, kill switch, retry cap of three | 6 |
| Dashboard misuse | Anyone on the network approves escalations or runs scenarios | Bind to 127.0.0.1, single bearer token, mutating routes require it | 9 |
| Supply chain | Malicious dependency | Pinned lock file, minimal dependency set, `uv` audit at M4 | 10 |

## 3. Secrets and configuration

- All secrets come from environment variables loaded by `pydantic-settings` from `.env`. `.env` is gitignored; `.env.example` lists every variable with a placeholder.
- Required: `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` (test mode only, ids start with `rzp_test_`), `RAZORPAY_WEBHOOK_SECRET`, `GEMINI_API_KEY` (optional when using Ollama or fixtures), `SALVAGE_DASHBOARD_TOKEN`, `SALVAGE_ENV` (`dev`, `demo`), `SALVAGE_KILL_SWITCH`.
- Startup refuses to run if the Razorpay key id does not start with `rzp_test_`. Live keys are never used in this project.
- Logging redacts any value that matches a configured secret and never logs request headers. Razorpay request ids and response ids are logged; bodies containing customer contact details are stored only in `webhook_events.raw_json`, which is excluded from log output and exports.
- A pre-commit hook runs a secret scanner (gitleaks or the `detect-secrets` baseline) before every commit. The repo is public, so this is mandatory, not advisory.
- Key rotation: rotating the Razorpay test key pair or the webhook secret in the dashboard and updating `.env` is the whole procedure; nothing is cached.

## 4. Webhook security

- Endpoint: `POST /api/webhooks/razorpay`, unauthenticated by design (Razorpay cannot present a bearer token), so verification is the authentication.
- Verification: HMAC-SHA256 of the raw request body using the webhook secret, hex encoded, compared with `X-Razorpay-Signature` using `hmac.compare_digest`. The body is read as bytes before any JSON parsing so the signature is computed over exactly what Razorpay signed.
- Idempotency: `X-Razorpay-Event-Id` is stored with a unique index; duplicates return 200 and do nothing. Out-of-order delivery is safe because normalisation is upsert-by-entity-id and state transitions are guarded by the state machine.
- Freshness: the payload's `created_at` must be within 15 minutes of receipt in `demo` mode; older events are stored, flagged and not acted on.
- Replay tool: the unsigned replay path exists only when `SALVAGE_ENV=dev` and is compiled out of the router otherwise.
- Tunnel: when a public URL is needed for the live demo, `cloudflared` or `ngrok` exposes only the webhook path; the dashboard and API stay on loopback.

## 5. Customer data and PII minimisation

- Customer identifiers: the database stores a salted SHA-256 `ref_hash` for joins and display; raw contact and email are stored only when they arrive in real webhook payloads and are masked to last four digits and domain in every API response and UI table.
- The ledger never contains contact, email, name or order notes. It references customers by `ref_hash` and orders by id.
- Exports (`ledger export`, results) contain no PII by construction; a test asserts that no export line matches a phone or email pattern.
- Synthetic customers in the simulator have synthetic contacts that follow real formats so the redaction code is exercised on realistic data.
- Retention: `data/` is gitignored; the demo database is rebuilt from the simulator, so there is no long-lived personal data.

## 6. Money-action controls

The agent has exactly two effects on the world: it can create, fetch and cancel a Razorpay Payment Link, and it can set a checkout display hint. Everything below keeps those effects bounded even when the model is wrong or hostile.

- The action schema cannot express an amount. `SEND_RECOVERY_LINK` params carry a case id; the executor reads the order amount from the database. There is no code path that takes an amount from model output.
- The allowlist is closed. The planner's output is validated against the enum; an unknown action fails validation and opens an escalation.
- The policy engine runs before every individual action, not once per plan, and re-reads state (including a fresh Razorpay order fetch for real orders) so a customer who paid in the meantime is never nudged.
- Caps: one open link per order, two nudges per customer per incident, three per seven days, link expiry equals case TTL, three API retries maximum.
- Circuit breaker: outbound failure rate above 30 percent in 10 minutes (minimum 10 actions) or link-pay rate below 2 percent after 50 sends pauses the incident and escalates.
- Kill switch: `SALVAGE_KILL_SWITCH=1` is checked at the start of every executor tick; when set, no outbound call is made and a ledger entry records each suppressed action. Detection and diagnosis continue so the dashboard still shows what would have happened.
- Human-in-the-loop: merchant-side and unknown causes, low-confidence diagnoses and circuit-breaker trips always land in the escalation queue. Approval is a dashboard action behind the token and is itself ledgered.
- Notify flags on Payment Links are always false. Razorpay never contacts the customer on Salvage's behalf; the simulated channel does, and only after the validator passes.

## 7. LLM boundary and prompt injection

Data that crosses to the model:

| Sent | Not sent |
|------|----------|
| Segment keys, counts, rates, error distributions, error codes, five `error_description` strings, sibling health, trend, minutes since onset | Names, contacts, emails, order notes, per-customer amounts, customer ids, anything typed by a customer |
| Reconciled diagnosis, action menu, eligible-customer counts | Any raw event payload |

`error_description` strings are produced by Razorpay, not by customers, but they are still untrusted text: they are placed inside a clearly delimited block with an instruction that the block is data, capped at 200 characters each, stripped of control characters, and limited to five. Order notes and customer names are never included anywhere in a prompt.

Defence in depth:

1. The model has no tools. Its output is a JSON object validated against a pydantic schema. It cannot call Razorpay, the database, or the channel.
2. Closed action enum and closed cause enum; free-text fields have length caps and are rendered as plain text in the UI.
3. The policy matrix means that even a valid-looking hostile plan (send links for a merchant-side fault) is refused and escalated.
4. Fault-injection tests include injection payloads in `error_description` and order notes that instruct the model to refund, discount or contact everyone; the tests assert the executor's actions are unchanged and the ledger records the refusal.
5. Free-tier providers may use inputs for training. The evidence packet is designed to be safe to publish; the redaction test enforces that.

## 8. Ledger integrity

- Append only: the writer exposes `append(kind, ref, payload)` and nothing else. There is no update or delete function anywhere in the codebase, and a test greps for `UPDATE ledger` and `DELETE FROM ledger` to keep it that way.
- Hash chain: `hash = sha256(seq || ts || kind || ref_type || ref_id || canonical_json(payload) || prev_hash)`. The first entry's `prev_hash` is a fixed genesis constant.
- Verification: `salvage ledger verify` recomputes the chain and reports the first broken sequence number. The dashboard exposes the same check behind a button. A property test mutates a random byte of a random entry and asserts verification fails.
- Export: `salvage ledger export` writes JSONL with the hashes included so a reviewer can verify offline with a twenty-line script (`scripts/verify_ledger.py`).
- What the ledger proves: that the record has not been altered after the fact. What it does not prove: that the process wrote the truth. That distinction is stated on the ledger page so the demo does not overclaim.

## 9. Dashboard and API access

- The API binds to `127.0.0.1:8000`; the Vite dev server binds to `127.0.0.1:5173` and proxies `/api`.
- Read routes are open on loopback. Mutating routes (`/api/escalations/{id}/decision`, `/api/sim/run`, `/api/sim/stop`, `/api/incidents/{id}/close`, kill switch toggle) require `Authorization: Bearer <SALVAGE_DASHBOARD_TOKEN>`.
- The token is entered once in the dashboard and held in memory, not in local storage.
- CORS allows only the Vite origin.
- There is no user model, no sessions, no roles. Adding them is out of scope and would be the first change for a real deployment.

## 10. Repository and dependency hygiene

- Public repo from day one, so every commit is treated as published: secret scanning pre-commit hook, `.env` and `data/` gitignored, fixtures reviewed for PII before commit.
- `uv.lock` committed; dependency set kept small (see Technical Architecture, section 14). `uv pip audit` or equivalent runs at M4 and the output is pasted into BUILD_LOG.md.
- The frontend has no runtime dependencies beyond React, the router and Tailwind; no analytics, no third-party scripts except Razorpay's `checkout.js` on the storefront page, loaded from Razorpay's own domain.
- CI runs with the fixture LLM provider and no secrets; the real end-to-end script is local only.

## 11. Incident handling during the demo

If something goes wrong on stage: set the kill switch (one environment variable, one restart, under 30 seconds), which stops all outbound actions while the dashboard keeps working; then rotate the test keys from the Razorpay dashboard if a credential is suspected. Both steps are rehearsed in M4 and the rehearsal is logged in BUILD_LOG.md.

## 12. Out of scope, deliberately

- Multi-user auth, roles, SSO.
- Encryption at rest beyond filesystem permissions (single laptop, synthetic data).
- Live-mode Razorpay keys, real customer channels, real money.
- Compliance certification claims. Salvage follows the spirit of consent, quiet hours and opt-out; it does not claim TRAI, RBI or PCI compliance, and the README says so.
