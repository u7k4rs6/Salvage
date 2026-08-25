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

## What is measured, and what is not

Zero policy violations across 200 runs. 45 fault injection attempts, 45 refused. Detection at 5 to
10 simulated minutes on the peak, with zero false alarms on the no-fault scenario across all seeds.

**The agent arm is unmeasured.** There was never a language model in this build environment, and a
rules-only diagnosis is deliberately assigned 0.5 confidence, below the 0.6 action threshold. So
the agent escalated every incident, took no customer-facing action, and recovered exactly what
doing nothing recovers. That column in the results is the no-model configuration, not the product.
The comparison it exists to make, cause-aware timing against blunt link-sending, has not been made.

What has been measured is the blunt baselines against each other, and they do well: about 1.8 times
the recovery of doing nothing, bought with roughly a thousand messages per simulated day. That
number is real and it is reported. It is also bought in a simulator that charges nothing for a
message except a 2.6 percent chance of an opt-out. No regulatory cost, no sender reputation, no
fatigue. The advantage of messaging everybody is priced at almost zero here, and a real merchant
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

Ten of the defects found in this build produced a number rather than a crash. Policies that could
see the future and declined to act on the customers who were about to pay anyway. Baselines that
were handed the agent's steering for free. A circuit breaker that measured a cap instead of a
policy. Evaluation fixtures written by the model being evaluated. The test suite was green through
almost all of it, because every component was doing its job correctly and the frame around them was
wrong.

That is the case for recording decisions in a form that can be re-read by someone who suspects the
frame, and for a results document that names what it has not measured before it shows a table.
`docs/WHAT_BROKE.md` is the full list.

## What comes next

One command with a model key fills in the agent arm, and the same sweep produces the comparison
this project was built to make. The two things after that are the ones this milestone could not
buy: a real Razorpay test-mode run end to end, which is written and refuses to run without
credentials, and a cost model for messages, so that contact volume is priced instead of assumed
free.
