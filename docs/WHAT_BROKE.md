# What broke

Every defect in this list was found and fixed during the build. They are ordered by what they cost,
and the ones that cost the most were not crashes. They were bugs that produced a number.

A crash announces itself. A measurement bug hands you a plausible table, and you put it in a
report. Ten of the defects below were of that kind, and most of them flattered somebody.

## Bugs that produced wrong numbers

### 1. The policies were reading the future

`_open_case_for` and the `case.order_unpaid` gate both tested `orders.status == 'paid'`. The agent
runs over a completed simulation, so an order the customer would pay at 22:30 already carried a
paid status at 20:10. A policy therefore declined to act on exactly the customers who were about to
come back on their own, and then took neither credit nor blame for them. Every link recovery it did
make was purely additive on top of an organic recovery it had quietly excluded itself from.

Fixed with `_paid_by(order, now)`, which asks whether the order was paid **by now** rather than
whether it was ever paid. `mark_order_paid` takes the minimum of the existing and new timestamp
instead of `COALESCE`, so a link paid at 20:10 beats an organic retry scheduled for 22:30, which is
what happens in the world where the link was paid.

This is the single worst bug in the project. It made every arm look better than it was, and it did
so in a way that no unit test on any component would have caught, because every component was
behaving correctly. The frame was wrong.

### 2. The baselines were getting the agent's steering for free

The channel filled the alternate-method slot from `customers.alt_method` for every policy, so B1's
message named a working alternative, and the response model applied the 2.2 multiplier meant for "a
nudge with a working alternate offered". PRD section 12 says the baselines differ from the agent in
exactly two things, cause-aware timing and method steering, and this handed one of the two to the
baselines. The comparison was rigged against the agent.

The alternate is now offered only when the policy steers, has a customer with another method, and
has an active checkout hint.

### 3. Whether a rail was broken was read off the detector's own incidents

A baseline acts under a synthetic incident that never closes, so every B1 nudge was scored as
landing in a still-broken rail and took the 0.3 penalty for the whole run. Worse than the penalty:
it made a baseline's measured outcome depend on how well the agent's detector had done. The
comparison was no longer between policies.

Whether a rail was up is a fact about the world, so the response model reads it from the
simulator's fault schedule. That is world state passed into the runner and used only inside
`_apply_customer_response`; no policy code path can see it.

### 4. The circuit breaker tripped after exactly 50 sends, in every run of every policy

PRD section 9 trips the breaker when fewer than 2 percent of links are paid after 50 sends. Read
literally that is true the instant the fiftieth send goes out, because a customer takes minutes to
hours to act on a link, so the pay rate at that moment is near zero by construction. Every arm was
capped at 50 links and the whole sweep was measuring a cap rather than a policy.

The pay rate is now measured only over sends older than six hours, the outer edge of the simulated
link-payment delay. Recorded as a reading of the rule rather than a change to it.

### 5. The sweep merge script silently dropped a scenario

The sharded sweep ran S0 to S4 as five background jobs and merged the shards. The merge built its
output by aliasing the first shard's payload, then assigned `merged["scenarios"] = []` before
extending it, which wiped S0 out of the header of the very dict it was reading from. The results
page and the report then described a four-scenario sweep as though that were the whole thing.

Fixed by building a fresh dict, and by deriving the scenario, seed and policy lists from the rows
rather than from a header that can disagree with them.

### 6. A stale results file reported "not measured" as "recovered nothing"

`/api/results` loaded a `main.json` written before the at-risk metrics existed. The metrics
dataclass defaults those fields to zero, so the console rendered a full set of at-risk columns
reading 0.00 for every arm. A zero that means "this was never measured" displayed as "this policy
recovered nothing" is the exact failure mode this project keeps finding.

The route now checks whether every row carries the at-risk fields and suppresses the columns with a
note when they do not, rather than rendering the defaults.

### 7. The primary table mixed two different populations in one cell

The at-risk table printed recovered revenue and message count over the at-risk order set, then a
third figure in the same cell, opt-outs, counted over the whole run. Read left to right it says the
opt-outs came out of the at-risk set. They did not, and there is no honest way to make them: a
policy messages orders inside and outside that set alike, and the simulator draws the opt-out at
send time.

Split into two tables with a paragraph saying why the scopes differ. My own defect, introduced
while fixing a scoping problem in the same table.

### 8. The evaluation fixtures were written by the model being evaluated

M2 shipped 46 diagnosis fixtures authored by the same model whose accuracy they were meant to
measure, with the scenario labels visible to their author. That is not a bug in code. It is a
measurement that cannot mean anything, and it would have produced a confident accuracy table.

All 46 were deleted and no number from them ever reached `docs/RESULTS.md`. The recorder that
refills the directory does so from a live provider with the labels withheld, and the isolation is
enforced by the code path rather than by discipline: a test walks the source tree and fails if any
file outside the evaluation runner reads the ground-truth tables.

### 9. Two smaller ones in the same family

`segment has recovered` was computed as `closed_at is not None`, which is always true when the
agent runs over a completed simulation, so the planner was told the fault was over while it was
still failing payments. Caught by reading a collected prompt rather than by a test.

`case.no_open_link` forbade second nudges rather than second links, conflating two different PRD
limits, so B2's second nudge never happened and B2 was silently measured as a slightly noisier B1.

## Bugs that would have hurt a customer

### The kill switch was not wired to the runs the dashboard starts

`_run_scenario` built its own argument list for the runner and left `kill_switch` out of it. An
operator could flip the switch, watch the top bar go red, start a run, and watch it send a thousand
messages. The switch itself worked; every gate around it worked; the wire between the operator and
the runner did not exist.

Found by rehearsing the kill switch end to end rather than by testing it. It is now read from
settings inside the runner call and is deliberately not a field on the request, because a run must
not be able to opt out of an operator control.

### An order paid while the link was in flight still got a message

The policy engine checked the order a moment before, but creating a Payment Link is a network call
and the customer can pay by another route during it. The security doc says a customer who paid in
the meantime is never nudged, and "in the meantime" includes that window. The executor now re-reads
the order between creating the link and sending the message, cancels the link, and closes the case
`PAID_ELSEWHERE`. Found by fault injection.

Two more fell out of the same test: the in-memory case dict was not updated with the new `link_id`,
so the cancel path had nothing to cancel; and a case whose order was paid while no timer was
scheduled to notice closed as `ABANDONED` with a live link against a paid order, which has the
shape of a real policy violation even though nothing wrong had happened.

### `salvage demo reset` ignored `--db` and emptied the default database

The `demo reset` subparser declared its own `--db`, which parses without complaint and then
overwrites the global flag with its own default of `None`. So `salvage --db scratch.db demo reset`
resolved to `data/salvage.db` and deleted the wrong database. It cost nothing here, because that
file is gitignored generated data, but the same shape pointed at anything that matters is
unrecoverable and gives no warning at all.

The subparser options are gone, the command prints the resolved path before deleting anything, and
a test walks the whole parser tree and fails if any subcommand defines `--db` again. That test was
checked against a planted copy of the bug before it was trusted.

## Bugs that only cost time

- One bad field type on the incident detail page blanked the entire console. The evidence packet
  carries `sibling_segments` as a mapping and the page called `.map` on it. Fixed, and every page
  is now wrapped in an error boundary, because a demo where one panel fails is better than a demo
  where one panel takes the screen with it.
- The first UI-driven run died on `UNIQUE constraint failed: customers.ref_hash`. A scenario is a
  whole world of 8,000 deterministic customers, and running a second one into a populated database
  collides at the first customer the two worlds share. The runner now resets by default.
- The first version of that reset died on `FOREIGN KEY constraint failed`, because `checkout_hints`
  references `incidents` and was ordered after it in the delete list. Reordered, and the reset now
  asserts `PRAGMA foreign_key_check` is empty afterwards, so a table added later without being
  added to the list fails loudly instead of leaving orphans.
- The ledger verify banner read "Chain intact Chain intact, 344 entries", because the server's
  message already opens with the verdict and the page added a label.
- Calibration and the sweeps wrote scratch databases to `/tmp`, which is a tmpfs on this machine,
  so a 200-run sweep was competing with the machine's memory.
- The first property tests filtered with `assume(action_type == SEND_RECOVERY_LINK)` and Hypothesis
  raised `FailedHealthCheck` for discarding four fifths of what it generated. It was right to: the
  tests would have run at a fraction of the coverage the example count implied. Rewritten to pin
  fields in the strategy rather than filter after the fact.
- `pkill -f "uvicorn salvage.api.app"` killed the shell that ran it, because the pattern matched the
  wrapper as well as the server.

## What the pattern is

Most of these were found by changing the frame rather than by running the tests: by asking what a
number means, by reading a prompt the model would see, by rehearsing a control instead of asserting
it, by injecting a fault at the one moment a check does not cover. The test suite was green through
almost all of them, and it was green because every component was doing its job correctly.

That is the argument for the two things this project spends the most effort on. The ledger, because
a decision that was recorded can be re-read later by someone who suspects the frame. And the
insistence in `docs/RESULTS.md` on naming what is not measured, because the number you have not
questioned is the one that will be wrong.
