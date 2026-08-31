# Salvage: the three-minute version

## The problem

A payment gateway does not usually fail all at once. It fails in a corner. One UPI handle starts
declining, or one card BIN range, or one bank's netbanking, and the merchant's overall success rate
moves two points, which nobody notices for an hour. In that hour a large D2C brand loses a few
hundred orders, and the customers behind them have already closed the tab.

The recovery that does happen today is undifferentiated. Send everyone who failed a payment link,
a few hours later, and hope. It works, and it works partly because a second chance to pay is worth
something no matter why the first one failed. But it is a blunt instrument aimed with no
information: it messages customers whose rail is still broken, it messages customers about faults
they cannot do anything about, and it treats a thousand messages a day as free.

## What Salvage does

A deterministic detector watches payment attempts in 15-minute windows, across a hierarchy of
segments from the merchant as a whole down to a single UPI handle or card BIN. When a segment
degrades past a calibrated threshold, on enough volume, for two consecutive windows, it opens an
incident and attributes it to the coarsest key that explains the failures.

An evidence packet is assembled from that incident and nothing else. A rules classifier and a
language model each name a root cause from the packet, and they are cross-checked: agreement raises
confidence, disagreement lowers it, and a diagnosis below 0.6 confidence cannot act. It escalates
to a human instead.

Above the diagnosis sits a policy engine with an allowlisted menu of four actions. The agent can
create a Razorpay Payment Link, send a nudge, set a checkout display hint, or escalate. It cannot
issue a refund, it cannot change a price, and it cannot call an endpoint that is not on the list.
A proposed message clears fourteen gates before it is sent, more when a cause-aware profile also
has to check the action against the diagnosis, and every decision, taken or refused, is written to
an append-only hash-chained ledger with the gate that decided it.

The result is an agent whose interesting property is not that it acts. It is that it declines to.

## What the demo shows

A scenario runs in the console in under twenty seconds: 100,533 payment attempts across 96,135
orders and 8,000 customers, one injected fault, detection, diagnosis, action, settlement and
measurement. The incident page shows the evidence the model saw, both verdicts side by side, and
the ledger slice for that incident. The ledger page verifies the chain and exports JSONL that an
offline script with no access to the database can re-verify.

Then flip the kill switch and run the same seed again. Identical world, same 282 orders at risk:
1,038 messages become zero, every action is refused with `global.kill_switch_off` named in its
ledger entry, and recovery falls to what customers manage on their own. Detection, diagnosis and
escalation keep running, because suspending an agent should not blind it.

## What is measured, and what it says

Zero policy violations across 200 runs. 45 fault injection attempts, 45 refused. Detection at 5 to
10 simulated minutes on the peak, with zero false alarms on the no-fault scenario across all seeds.

**The agent arm is measured now**, against a live Gemini, from diagnosis fixtures recorded blind:
the recorder builds each evidence packet through the same call the agent makes, which cannot reach
the ground-truth tables, hands the model a type carrying the prompt and its hash and nothing else,
and refuses any prompt in which a scenario id, a seed or a cause name appears.

Over the at-risk order set, mean of 10 seeds, revenue in rupees against messages sent:

| scenario | agent | best baseline | 
|---|---|---|
| S1 issuer outage | **2,21,154 from 83 messages** | 1,75,050 from 261 (B2) |
| S2 BIN auth failure | **1,20,065 from 44 messages** | 93,255 from 140 (B2) |
| S3 gateway degradation | **4,78,668 from 422 messages** | 4,72,828 from 492 (B2) |
| S4 merchant misconfiguration | 90,128 from 0 messages | 1,65,041 from 272 (B2) |

On S1 the agent recovers 26 percent more than the best blunt baseline from 32 percent of its
messages, and on S2 it recovers 29 percent more from 31 percent of its messages. **S3 is not a win
and should not be read as one:** the difference is 5,840 rupees on a paired standard deviation of
15,993 across ten seeds, the agent loses some seeds outright, and its message count is 86 percent
of B2's rather than a third. Call it a tie reached with slightly fewer contacts.

**The baselines beat the agent on whole-run revenue on every scenario, by 29 to 44 percent.** On S1
they recover about 17.3 lakh to the agent's 11.0 lakh. They win it by messaging a thousand
customers a day whose failures have nothing to do with any incident. The agent sends 90. On S0, the
day nothing breaks at all, the baselines send about a thousand messages each and the agent sends
none, because there is no incident to act on. Which of those two readings a merchant should prefer
depends on what a message costs them, and this simulator charges almost nothing for one, which
flatters the baselines rather than the agent.

Where does the agent's at-risk margin come from? Mostly from steering customers onto a working
instrument in the same session, and partly from timing links to land after a rail recovers.
**On this workload the language model did not detectably contribute to recovery**, and this build
measured that rather than assuming it. Over 41 incidents the rules classifier alone is right 90.2
percent of the time and the model-assisted diagnosis 97.6 percent. The `echo` arm in the results is
the agent with its model replaced by a stub that repeats the rules verdict, everything else
identical; paired across ten seeds it recovers 16,066 rupees more on S1, 6,081 less on S2, 15,266
less on S3 and exactly the same on S4. The signs disagree, no scenario clears a paired t, and the
four sum to roughly minus five thousand rupees.

The mechanism is structural. Every incident the rules get wrong they get wrong by answering
`unknown`, and an unknown cause is allowed nothing but escalation, so both arms escalate the same
incidents by different routes. On every incident where the agent acts, the rules were already
right. And the residual is a confound rather than a result: the reconciled cause is identical in
the 37 of 41 incidents the rules get right, and what differs is the confidence number in the
planner's prompt, 0.70 against 0.95.

Two honest reasons it could come out differently elsewhere. The rules classifier was written
against these exact five scenarios, so it is being asked about the distribution it was designed
for. And 41 incidents cannot resolve a small effect; anything smaller than the seed-to-seed spread
would be invisible here.

The gate is doing the work, and it works in one direction. A probe against a model that returns a
confident wrong cause recovers exactly what doing nothing recovers, because every action it
proposes is refused and the incident escalates. So being wrong is caught and costs nothing; being
right beyond the threshold buys nothing at this sample size. A harder incident mix is where a model
would earn its place and this sweep does not contain one.

**S4 is a loss in that table and it is the most useful row in it.** The cause is a merchant
misconfiguration, no customer can pay their way around it, so the agent contacts nobody and files
an escalation. It therefore recovers exactly what doing nothing recovers, and both link-sending
baselines beat it by messaging around two hundred customers about something none of them can fix.

That is the cost of restraint measured against no benefit, because until this milestone an
escalation reached a human and the world carried on failing for the full three hours. So the second
thing M5 does is model the fix as a swept parameter: an escalation filed at time t repairs the
faulting method at t plus T, and T is swept rather than chosen, because how fast a merchant acts is
not a fact about Salvage.

The answer is that it barely matters when, only whether. At every response time from 15 minutes to
two hours the agent lands between 2,67,435 and 2,77,080 rupees against B2's 1,83,115, and it does
it sending nothing at all. Even the slowest response swept puts it 46 percent ahead of the best
baseline on zero messages. Past the fault's own 180 minute duration the fix is worth exactly
nothing, because the world has already recovered on its own.

Two caveats, both stated in the results rather than buried. Only an arm that escalates can be
repaired, so B1 and B2 cannot benefit by construction, and a real merchant might well notice a
wholly dead payment method without an agent telling them. And the mechanism is deliberately the
smaller of the two things it could be: it gives customers one more chance to come back, and does
not stop the payments that would fail after the repair, so it understates what a fix is worth for
the only arm that can trigger one.

Everything above is bought in a simulator that charges nothing for a message except a 2.6 percent
chance of an opt-out. No regulatory cost, no sender reputation, no fatigue. That pricing flatters
the baselines, not the agent, so the contact-volume gap is if anything understated: a real merchant
sending 1,436 messages a day would be having a different conversation before they had this one.

## The number worth taking away

The same fault, moved from the evening peak to 03:30 in the morning, is not detected at all. Not
slowly. Not misattributed. **Zero out of twenty, across four scenarios and five seeds each.**

The arithmetic is not subtle once written down. The diurnal curve puts the overnight trough at
about one thirtieth of peak arrival, so at 12,000 attempts a day the whole merchant sees about
eleven attempts in a 15-minute window. The detector will not evaluate any segment with fewer than
20 attempts in a window, so at 03:30 there is no key it can test, including the merchant-wide one.
The fault happens, the payments fail, and there is nothing to test.

So the 15-minute promise is a promise about the evening peak. Overnight, at this merchant size,
this detector does not fire. The same wall shows up in volume: at 1,500 attempts a day, half the
faults are never detected at all, and the boundary where a single-instrument fault becomes reliably
detectable inside 15 minutes sits somewhere between 5,000 and 12,000 attempts a day.

Nothing was tuned against that result. The thresholds were frozen before the off-peak variant
existed. It is in the pitch rather than in an appendix because it is the most useful thing the
project found: it says which merchants this works for and which it does not, and any version of
this that claims to work everywhere has not looked.

## Why the ledger is the load-bearing part

Thirteen of the defects found in this build produced a number rather than a crash. Policies that
could see the future and declined to act on the customers who were about to pay anyway. Baselines
that were handed the agent's steering for free. A circuit breaker that measured a cap instead of a
policy. Evaluation fixtures written by the model being evaluated. The test suite was green through
almost all of it, because every component was doing its job correctly and the frame around them was
wrong.

Four of them surfaced in a single afternoon, the first time a real model was ever plugged in. The
worst: on S4 the model diagnosed the misconfiguration correctly and planned an escalation, wrote
its reasoning in the plan's rationale rather than in the action's params, and a validator threw the
action away for it. The plan came back empty and the agent did nothing at all. On the sweep that
read as an agent choosing restraint. It was equalling B0 by saying nothing.

That is the case for recording decisions in a form that can be re-read by someone who suspects the
frame, and for a results document that names what it has not measured before it shows a table.
`docs/WHAT_BROKE.md` is the full list.

## What comes next

Two things this build could not buy. A real Razorpay test-mode run end to end, which is written and
refuses to run without credentials. And a cost model for messages, so that contact volume is priced
rather than assumed free: every contact-efficiency number here is measured in a world where the
only thing a message costs is a small chance of losing the customer, which is the assumption most
worth attacking.

Beyond that, the honest next step is not a feature. It is the operating envelope: this detector
works at the evening peak on a merchant doing around 12,000 attempts a day, and the results say
plainly where it stops working. Making it work overnight, or at 1,500 attempts a day, means a
longer window or a lower attempt floor, and both trade against the zero false alarms.
