# Salvage: Product Requirements Document

Version 0.1, 24 August 2026. Owner: Utkarsh Bahuguna. Status: locked for build.

## 1. Summary

Salvage is an AI agent for merchants on Razorpay that notices when payments start failing in clusters, works out why, and wins the money back inside hard limits. It is the Track 03 (AI Revenue Recovery) entry for the Razorpay AI Buildathon 2026, built to the track's first example direction: payment degradation, root cause, recovery action.

The track's bar is: measured money recovered across a batch, with compliant escalation, stopping rules, and an audit trail. Every requirement in this document traces to one of those four clauses (section 5).

Deadline: applications close 5 September 2026. Solo builder. Submission: public GitHub repo, 5-minute pitch video, architecture documentation, and a written account of what broke during the build and how it was fixed.

## 2. Problem

When a payment fails at checkout, the merchant loses the sale unless the customer comes back on their own. Failures rarely arrive one at a time. A bank's UPI rail degrades for an hour, a card issuer starts rejecting authentication for a BIN range, a gateway times out under load, or the merchant's own configuration breaks. Three things then go wrong in sequence:

1. Detection is slow. The dashboard shows a dip. Somebody notices it hours later.
2. Diagnosis is guesswork. Was it the bank, the gateway, or us? The answer decides whether to call Razorpay, fix a setting, or wait.
3. Recovery is unbounded and blunt. The usual fix is a reminder blast to everyone who failed, which pushes customers back into the same failing rail, ignores consent, and leaves no record of who was contacted, how often, or why.

Salvage closes that loop with a deterministic detector, an LLM-assisted diagnosis that is cross-checked by rules, an allowlisted menu of interventions gated by a policy engine, and an append-only ledger.

## 3. Goals

| ID | Goal | Bar clause |
|----|------|-----------|
| G1 | Detect a payment degradation within 15 simulated minutes of onset, with fewer than 0.2 false incidents per clean day | measured recovery (precondition) |
| G2 | Classify root cause into six classes with measured accuracy against simulator ground truth | measured recovery, escalation |
| G3 | Recover measurably more revenue than three baselines across a scenario batch, with zero policy violations | measured recovery, stopping rules |
| G4 | Escalate to a human with an evidence packet when the cause is merchant-side or diagnosis confidence is low | compliant escalation |
| G5 | Record every event, decision, gate check, API call and outcome in a tamper-evident ledger | audit trail |
| G6 | Ship a harness that tries to break G3, G4 and G5, and publish what it found | all four |

## 4. Non-goals (v1, explicit)

- Checkout abandonment before a payment attempt. There is no intent signal; it is a different product.
- Subscriptions, mandates, UPI Autopay retry sequencing.
- B2B receivables, invoices, promise-to-pay tracking.
- Voice, WhatsApp, SMS or email as real channels. All customer-facing channels are simulated; the message content is real and validated.
- Discounts, coupons, refunds, or any change to the amount owed.
- Debiting a customer. Salvage never pulls money. It creates Payment Links and checkout hints, nothing else.
- Multi-merchant or multi-tenant operation. One merchant, one Razorpay test-mode account.

## 5. The bar, clause by clause

| Clause | What Salvage does | Where the panel sees it |
|--------|-------------------|-------------------------|
| Measured money recovered across a batch | Six scenarios, at least five seeds each, agent versus three baselines, mean and standard deviation | `docs/RESULTS.md`, Results page, first minute of the pitch |
| Compliant escalation | Human queue with evidence packet and proposed action; merchant-side and low-confidence incidents always land there; consent, quiet hours, frequency caps and opt-out enforced in code | Escalation inbox, ledger entries, policy tests |
| Stopping rules | Per-order TTL, per-customer caps, hard-decline stop, defer-while-cause-active, circuit breaker, kill switch | Policy engine source, property tests, one rule tripped live in the pitch |
| Audit trail | Hash-chained append-only ledger with a verify command; per-incident timeline in the UI | Ledger viewer, `verify-ledger` output |

## 6. Users and jobs

Primary user: a merchant ops or finance person at a mid-size D2C store on Razorpay. Jobs to be done:

- Know within minutes that payments are breaking, and for which customers.
- Know whether to call Razorpay, fix a setting, or wait it out.
- Recover the lost sales without annoying customers or breaking rules.
- Show, afterwards, exactly what the system did and why.

Secondary user: the buildathon panel. Jobs: confirm the metrics are honest, confirm the agent is bounded, confirm the audit trail is real, see one failure handled gracefully.

## 7. The loop

1. Detect (deterministic). Ingest Razorpay-shaped payment events. Maintain per-segment success rates on sliding windows against a rolling baseline. Segment keys: method, bank or UPI handle, card BIN prefix, card network, card issuer, error step. Open an incident when the drop is statistically significant, exceeds a minimum effect size, and persists for two consecutive windows. Track at-risk revenue per incident and open a recovery case per failed order.
2. Diagnose (LLM step 1, rules cross-check). Build an evidence packet from the incident's error distribution versus baseline. The LLM returns a structured root cause with confidence and a rationale that cites evidence fields. A rules classifier runs in parallel. Disagreement lowers confidence; low confidence escalates.
3. Decide (LLM step 2, policy validation). The LLM proposes a plan from an allowlisted menu (section 8). The policy engine validates the plan against the cause-to-action matrix, caps, consent, quiet hours and stopping rules. Anything outside the menu is refused, logged and escalated.
4. Execute. Each recovery case runs an explicit state machine with idempotency keys, retries with backoff on Razorpay API errors, and real test-mode API calls: create, fetch and cancel Payment Links; fetch the Order to confirm it is still unpaid immediately before any action.
5. Close. Track outcomes (paid via link, paid on organic retry, not recovered, opted out, escalated). Close the incident when the segment recovers and every case is terminal. Produce a recovery report.

## 8. Allowlisted interventions

| Action | What it does | Allowed for | Bound |
|--------|--------------|-------------|-------|
| STEER_METHOD | Sets a checkout display hint that hides or de-prioritises the failing method or instrument and surfaces alternatives, on the storefront and on recovery links | issuer_outage, auth_failure_bin | Applies only to the affected segment; expires when the incident closes |
| SEND_RECOVERY_LINK | Creates a Razorpay Payment Link for the exact failed order amount and sends a templated message through the simulated channel | issuer_outage, auth_failure_bin, gateway_degradation (after recovery), customer_side | One open link per order; consent required; quiet hours; per-customer caps |
| DEFER_UNTIL_RECOVERED | Holds nudges for affected customers until their segment's success rate recovers, then sends | issuer_outage, auth_failure_bin, gateway_degradation | Per-order TTL still applies |
| ESCALATE_HUMAN | Opens a ticket with the evidence packet and proposed action; waits for approve or reject | merchant_config, unknown, any low-confidence incident, any circuit-breaker trip | Nothing customer-facing happens until a human decides |
| NO_ACTION | Records that nothing will be done, with the reason | customer_side below the value threshold, opted-out customers | Logged like every other action |

Message content: templates in English and Hinglish with LLM-filled slots (order reference, alternate method suggestion, expiry). A validator rejects any message containing a promise, a discount, urgency language beyond the link expiry, or a missing opt-out line.

## 9. Stopping rules and bounds

All enforced in code. None depend on the model behaving.

- Max one open recovery link per order. If the order gets paid any other way, the link is cancelled and the case closes as PAID_ELSEWHERE.
- Max two nudges per customer per incident; max three per customer per rolling seven days across incidents.
- No nudges without a consent flag. Opt-out is honoured immediately and permanently.
- Quiet hours 21:00 to 09:00 IST (configurable). Sends due in quiet hours are queued for 09:00.
- Never nudge while the diagnosed cause is still active for that customer's method. Defer instead.
- Hard-decline reasons (card blocked, account closed, suspected fraud, invalid instrument) get no retry and no link.
- Per-order TTL 72 hours, then ABANDONED.
- Circuit breaker: if outbound actions fail above 30 percent in a rolling 10 minutes (minimum 10 actions), or if fewer than 2 percent of links are paid after 50 sends within an incident, pause that incident and escalate.
- Kill switch: `SALVAGE_KILL_SWITCH=1` stops all outbound actions; detection and diagnosis continue.
- Amount on every link equals the original order amount. No other amount is representable in the action schema.

## 10. Scenarios

Each scenario is a parameter set applied to the simulator (see Technical Architecture, section 8) on top of seven simulated days of warm-up traffic, followed by one evaluation day. Ground truth per payment attempt is whether it was fault-caused or organic, and the incident's true cause.

| ID | Fault | Correct behaviour | Status |
|----|-------|-------------------|--------|
| S0 | None. Normal noise only | Detector stays quiet; nothing sent | Required (calibration) |
| S1 | One UPI handle's issuer fails for 90 minutes; other handles healthy | Steer to other methods; defer customers who only have that handle; links after recovery | Required |
| S2 | One card BIN range fails at authentication for 2 hours | Steer away from that issuer; links with cards hidden | Required |
| S3 | Gateway degradation: intermittent timeouts across all methods for 60 minutes | Defer everything; informational escalation; links after recovery | Required |
| S4 | Merchant misconfiguration produces business-source errors on one method | Escalate to human only; no customer contact | Required |
| S5 | Customer-side long tail: insufficient funds, wrong OTP, user cancelled; no cluster | No incident; light-touch single link above the value threshold, otherwise nothing | Stretch |

## 11. Metrics and success criteria

Reported per scenario and seed, at least five seeds, mean and standard deviation, agent versus baselines B0 (no action), B1 (immediate link to every consented failed order), B2 (fixed-interval retry prompts at 1 hour and 6 hours regardless of cause).

| Metric | Definition | Target |
|--------|-----------|--------|
| At-risk revenue | Sum of failed-order amounts inside incident windows, unpaid at detection | reported |
| Recovered revenue | Amounts paid on recovery links or organic retries after intervention, attributed by case | agent beats B1 and B2 on S1, S2, S3; agent equals B0 on S4 (no contact) |
| Recovery rate | Recovered cases divided by eligible cases | reported |
| Contact efficiency | Messages sent per 1,000 rupees recovered | agent lower than B1 |
| Time to detect | Sim minutes from fault onset to incident open | under 15 |
| Root-cause accuracy | Diagnosis matches ground truth, rules-only and LLM-assisted reported separately | LLM-assisted at least as good as rules-only |
| Escalation precision | Escalations that a human would agree were warranted, judged against scenario truth | above 0.8 |
| Policy violations | Any action that breaks a section 9 rule | zero, across all runs and the harness |
| False alarms | Incidents opened on S0 per simulated day | under 0.2 |

Plus one real end-to-end run recorded in the results: a real test-mode Order, a real Payment Link created by the agent, paid with a Razorpay test instrument, webhook received and verified, ledger entries shown.

## 12. Measurement honesty

The simulator is the measuring instrument, so its assumptions are part of the result.

- Every simulator parameter lives in one YAML file with the assumption written beside it. There are no hidden constants.
- The agent's advantage must come from diagnosis-driven timing and steering (not nudging into a dead rail, offering a working alternative), not from tuned probabilities. The results include a sensitivity sweep over the response-model multipliers and one adversarial parameter set where naive immediate retry does as well as the agent. That case is reported, not hidden.
- Baselines respect consent and quiet hours too. They differ from the agent only in what the agent is supposed to be good at: cause-aware timing and method steering.
- Root-cause accuracy is reported for rules-only and LLM-assisted diagnosis. If the LLM adds nothing, the results say so.
- No result in RESULTS.md may come from a single seed.

## 13. Milestones

| Milestone | Days | Exit criteria |
|-----------|------|---------------|
| M1 Foundation | 1 to 3 | Simulator runs S0 to S4 with seeds and ground truth. Ledger with hash chain and verify command. Detector fires on S1 to S4 within target and stays quiet on S0 across five seeds; calibration table printed. Webhook receiver with signature verification, dedupe and record/replay. Tests green. BUILD_LOG.md started |
| M2 Brain and hands | 4 to 7 | Evidence packets, rules classifier, LLM diagnosis and planner with schemas, policy engine, per-order state machine, execution against Razorpay test mode, simulated channel with validated templates. One real end-to-end link paid |
| M3 Harness and results | 8 to 9 | Property tests, fault injection suite, baselines, evaluation runner, RESULTS.md with all tables, sensitivity and adversarial sets |
| M4 Show | 10 to 12 | Dashboard pages per Frontend Spec, pitch video recorded, README and architecture polished, BUILD_LOG.md turned into the "what broke" write-up |

## 14. Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Simulator circularity: the response model rewards the agent's own choices | Panel discounts the numbers | Section 12: explicit parameters, sensitivity sweep, adversarial set, honest baselines |
| Free-tier LLM rate limits during eval | Blocked runs | Incident-level calls only (tens per run), response cache by evidence hash, fixture mode for tests and repeatable evals, Ollama fallback |
| Test mode cannot produce batch payments or simulate issuer outages | Gap between sim and real | Hybrid: Orders and Payment Links are real test-mode objects; payment attempts in the batch are simulated events shaped like Razorpay's; one real end-to-end run proves the plumbing |
| UPI Collect deprecation may affect test UPI ids | Real end-to-end run fails on UPI | Use a Razorpay test card for the real run; verify test UPI availability in M2 |
| Laptop memory pressure | Dev environment crashes | SQLite, no containers, Vite not Next, one process at a time during eval |
| Time | Scope creep kills M3 | S5 and every "nice to have" is already marked stretch; M3 is not negotiable because the results table is the pitch |

## 15. Submission plan

- Repo: public, MIT, README with a 90-second explanation, architecture section linking to `docs/`, and the results table inline.
- BUILD_LOG.md: dated entries from day one of coding. Each entry: what broke, how it was found, what fixed it, what test now guards it. This becomes the "what broke and how we recovered" submission answer without rewriting.
- Pitch video, 5 minutes:
  - 0:00 the problem in one sentence and one screenshot of a real dip (30 s)
  - 0:30 the results table: agent versus baselines, policy violations zero, false alarms (60 s)
  - 1:30 live run of S1: detection, diagnosis with confidence, plan, gate results, links created (90 s)
  - 3:00 one failure handled live: the model proposes a refund, the gate refuses it, the incident escalates, the ledger shows both (45 s)
  - 3:45 ledger verification and the escalation inbox (45 s)
  - 4:30 what broke during the build (30 s)

## 16. Open questions

- Does Razorpay test mode still accept test UPI ids after the February 2026 UPI Collect deprecation? Decides which instrument the real end-to-end run uses.
- Gemini 2.5 Flash versus Flash-Lite as the primary free-tier model. Default is Flash with automatic fallback to Flash-Lite on 429; confirm the model ids and quota in AI Studio at setup.
- Whether the `razorpay` Python SDK covers Payment Links create, fetch and cancel cleanly, or whether direct `httpx` calls are simpler. Decide in M1 by reading the SDK source.
