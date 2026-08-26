# Salvage: submission

Razorpay AI Buildathon 2026, Track 03. An AI agent that notices when payments start failing in
clusters, works out why, and wins the money back inside hard limits.

Everything below is measured in a simulator that ships with the repository, from a 250-run sweep
whose raw output is in `data/results/` and whose per-run rows are in `docs/results_by_run.csv`.
The numbers that went against the agent are in this document too, in the same size type.

## What it does

A deterministic detector watches payment attempts in 15-minute windows across a hierarchy of
segments, from the merchant as a whole down to a single UPI handle or card BIN. When a segment
degrades past a calibrated threshold, on enough volume, for two consecutive windows, it opens an
incident and attributes it to the coarsest key that explains the failures.

An evidence packet is assembled from that incident and nothing else. A rules classifier and a
language model each name a root cause from the packet and are cross-checked: agreement raises
confidence, disagreement lowers it, and anything below 0.6 escalates to a human instead of acting.

Above the diagnosis sits a policy engine with an allowlisted menu of four actions: create a
Razorpay Payment Link, send a templated nudge, set a checkout display hint, or escalate. It cannot
refund, discount, or change what a customer owes, because no amount field exists in the action
schema. A proposed message clears fourteen gates before it is sent, and every decision, taken or
refused, is written to an append-only hash-chained ledger with the gate that decided it.

## The headline, and the number that undercuts it

Recovered revenue over the at-risk order set, mean of 10 seeds, revenue in rupees against messages
sent. An order is at risk when its first attempt failed inside a fault window and on the instrument
that fault was breaking. That set is computed from the world's fault schedule, so it is identical
for every arm and a test asserts the sets themselves.

| scenario | agent | echo | B0 | B1 | B2 |
|---|---|---|---|---|---|
| S1 issuer outage | 2,21,154 / 83 msg | 2,37,221 / 131 msg | 93,947 / 0 | 1,47,797 / 164 | 1,75,050 / 261 |
| S2 BIN auth failure | 1,20,065 / 44 msg | 1,13,983 / 29 msg | 50,095 / 0 | 79,263 / 88 | 93,255 / 140 |
| S3 gateway degradation | 4,78,668 / 422 msg | 4,63,403 / 379 msg | 3,01,760 / 0 | 4,20,743 / 312 | 4,72,828 / 492 |
| S4 merchant misconfiguration | 90,128 / 0 msg | 90,128 / 0 msg | 90,128 / 0 | 1,57,696 / 178 | 1,65,041 / 272 |

The agent beats the best blunt baseline by 26 percent on S1 using a third of its messages, and by
29 percent on S2 using under a third. S3 is a tie, not a win: 5,840 rupees on a paired standard
deviation of 15,993, with the agent losing seeds outright. S4 is a loss by design, and the most
useful row here.

**Scoped to the whole day instead, the agent recovers 29 to 44 percent less than the best
baseline, on every scenario.** On S1 they recover about 17.3 lakh against the agent's 11.0 lakh. They win by messaging
about a thousand customers a day, most of whose failures have nothing to do with any incident. Both
readings are true. Which one a merchant should want depends on what a message costs them, and this
simulator charges almost nothing for one, which flatters the baselines and not the agent.

## Three results that went against us, kept because they are true

**The language model's diagnosis accuracy is worth nothing here.** Over 41 incidents the rules
classifier alone is right 90.2 percent of the time and the model-assisted diagnosis 97.6 percent.
The `echo` column above is the agent with its model replaced by a stub that repeats the rules
verdict; paired across ten seeds it is ahead on S1, behind on S2 and S3, identical on S4, and the
four sum to roughly minus five thousand rupees. Every incident the rules get wrong they get wrong
by answering `unknown`, and an unknown cause is allowed nothing but escalation, so both arms
escalate the same incidents. The gate still earns its keep in the other direction: a model that
returns a confident wrong cause recovers exactly what doing nothing recovers, because every action
it proposes is refused.

**S4 is a loss until somebody acts on the escalation.** The cause is a merchant misconfiguration,
no customer can pay around it, so the agent contacts nobody and files a ticket while both baselines
message two hundred customers about something none of them can fix. `escalation_fix_minutes` models
the repair as a swept parameter rather than a chosen one; inside the outage the agent lands 46
percent ahead of B2 on zero messages, and after the outage a fix is worth nothing at all. Only an
arm that escalates can be repaired, and a real merchant might notice a dead payment method without
an agent telling them.

**The detector does not work overnight, and the results say so first.** The same fault moved from
the evening peak to 03:30 is not detected at all: zero of twenty, across four scenarios and five
seeds each. At that hour the whole merchant sees about eleven attempts in a 15-minute window and
the detector will not evaluate a segment below twenty. It is arithmetic, not a threshold, and it
says which merchants this approach works for.

## What the safety story is worth

Zero policy violations across all 250 runs. 45 fault injection attempts, 45 refused, including a
planner asking for a 50 percent discount, a prompt injection inside an error description, a
replayed webhook and a forged signature. The kill switch was rehearsed rather than asserted: same
world, same seed, 1,038 messages become zero and detection, diagnosis and escalation keep running.
The ledger verifies offline through a script with no database access.

## What is not measured

- No real Razorpay call has ever been made. `scripts/e2e_real_link.py` is written and refuses to
  run without test-mode credentials, which this build environment did not have.
- A message costs nothing here but a 2.6 percent chance of an opt-out. No DLT registration, no
  sender reputation, no complaint cost.
- **Two of the five scenarios key on payload fields that may not be present in production Razorpay
  payloads.** S2 detects on `card_bin6` and S1 on `upi_handle`, the primary segment keys for those
  scenarios. The documented payment entity carries no `iin` on its card object, only a `token_iin`
  that is null in the published sample and names a network token rather than the card, so
  `card_bin` is None from a documented payload; and the webhook docs publish no payment.failed
  sample for UPI at all while warning twice that `vpa` may be absent on exactly that event. This
  affects no number reported here, because the simulator emits both fields and every arm faces the
  same payloads, but the detector's segment keys would have to be re-derived against real traffic
  before this ran in production, and that has not been done. The fallback is the coarser keys the
  payload does carry, card network, card issuer and the method, which enlarge the denominator and
  dilute the excess across healthy siblings, so by the operating envelope it buys later detection
  or none. Not solved.
- One model, one afternoon: every diagnosis fixture came from `gemini-2.5-flash`.
- No hybrid arm. The best question a reviewer can ask is why a merchant should not simply run B1
  and let the agent suppress it inside incident scope, and this repository does not answer it.

## Reading order

`docs/RESULTS.md` for the numbers and their caveats, `docs/AUDIT.md` for an adversarial read of
this repository written against itself, `docs/WHAT_BROKE.md` for the thirteen defects that produced
a wrong number rather than a crash, and `docs/BUILD_LOG.md` for every decision with its reason.
