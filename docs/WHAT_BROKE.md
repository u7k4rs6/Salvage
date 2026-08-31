# What broke

Every defect in this list was found and fixed during the build. They are ordered by what they cost,
and the ones that cost the most were not crashes. They were bugs that produced a number.

A crash announces itself. A measurement bug hands you a plausible table, and you put it in a
report. Thirteen of the defects below were of that kind, and most of them flattered somebody.

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

**It was not fully fixed. See entry 14.** The fix landed on `_open_case_for`, the path the
baselines take, and on the `case.order_unpaid` gate. `_open_cases`, the path the agent takes, kept
reading the status column for another seven milestones.

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

## Four more, on the day a real model arrived

A Gemini key turned up in M5, after two milestones in which the agent arm had never once run with
a model. Four defects surfaced in a single afternoon, all in code that a green test suite had been
passing for weeks, and all four found by running the thing rather than by testing it.

### 10. The rationale validator demanded names the model was never shown

A diagnosis must cite at least two evidence fields by name, and the check was written against
`EvidencePacket.model_fields`. That is not the list the model sees. The packet prints
`error_source`, `error_step`, `error_reason`, `failure_rate` and `baseline_failure_rate`; the
fields behind them are `error_source_dist`, `error_step_dist`, `error_reason_dist`, `rate` and
`baseline_rate`. The system prompt then teaches the printed vocabulary in its taxonomy section.
The model was being told one set of names and marked against another.

**16 of 41 blind recordings failed on it**, each after spending its one documented retry being
told to use names it had never been given. Left alone, the LLM column would have been a model that
looks incapable of following an instruction, and the incidents behind those sixteen would have
escalated and read as an agent choosing restraint.

Only a real model could find this. The 46 fixtures M2 shipped were written by a model that had
been shown the dataclass, so they cited `error_source_dist` and sailed through.

### 11. Every recovery link a model planned was silently dropped

`SendRecoveryLinkParams` requires a `case_id`. The planner is asked for one action and a scope, and
the executor fans that out over the cases the scope selects, so a case id is not something the
planner can know or is ever asked for. `plan_incident` validated the planner's params against that
model, found no `case_id`, dropped the action, and recorded the drop in a `planner_error` field
that nothing read.

With a model present the agent could steer, defer, escalate and do nothing, and could never send a
recovery link. It was found on the first real agent run, where the plan's own rationale said
"sending a recovery link offers a direct path to complete their payment" and the run created zero
links.

The plan-time check now injects a placeholder case id for the actions whose params model has that
field, and the executor fills the real one per case. It still drops an action carrying an invented
`amount` or `discount_percent`, which is what it was for. The first version of the fix injected the
placeholder into every action and broke `STEER_METHOD`, whose params model forbids extra fields;
an existing test caught that within a minute.

### 12. The agent answered a merchant misconfiguration with total silence

The worst of the four, and the one that had already reached a published table before it was found.

On S4 the model diagnosed the misconfiguration correctly at 0.95 confidence and planned an
`ESCALATE_HUMAN`. It wrote its reasoning in the plan's `rationale` field: "Merchant-side
configuration issue. Hard rules dictate no customer contact for merchant-side causes. Escalating
internally for resolution." It left the action's own `params` empty. `EscalateHumanParams` requires
a `reason`, so the action failed validation and was dropped, and the plan came back with no actions
at all.

The agent then did nothing. No customer contact, which is correct and is the whole point of S4. And
no escalation, which is the one response the design does not allow: a merchant misconfiguration is
precisely the case where a human has to be told, because nothing a customer does will fix it.

On the sweep this read as an agent equalling B0 through principled restraint. It was equalling B0
by saying nothing, and the S4 row of a completed 200-run sweep had already been written up that way
before an escalation count of zero looked wrong enough to chase.

Two fixes. An absent `reason` on `ESCALATE_HUMAN` or `NO_ACTION` is filled from the plan's own
rationale, because an action is not wrong for putting its explanation in the field next door, and
the model's own words are more use to the human reading the escalation than a generated
placeholder. And a plan whose actions are all dropped now falls back to `default_plan`, which is
what that function has always documented itself as being for: "a planner that cannot plan must not
fall back to doing something to customers; it falls back to asking a person." It had only ever been
reached when the provider was absent or raised, never when validation threw everything away.

### 13. The escalation fix scoped its population backwards, and this one is mine

The M5 mechanism gives every order a repaired fault put at risk one further chance to come back.
The first version gave it only to orders that had already failed when the repair landed, which
seemed obviously right and made a 15 minute fix score worse than a 120 minute one. A fast fix
simply has fewer failures behind it, and the failures in front of it are precisely the ones it
should have prevented; the simulator cannot show them not happening, because the attempt stream is
generated before any policy runs.

Scoping it that way turned a limitation of the instrument into an inverted curve, which is worse
than a missing result: it would have said an operator should respond to escalations slowly. The
monotonicity test caught it. The mechanism now covers the fault's whole at-risk set, and
`docs/RESULTS.md` says plainly that it still understates what a fix is worth.

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
it, by injecting a fault at the one moment a check does not cover, by plugging in a real model and
watching what it actually did. The test suite was green through almost all of them, and it was
green because every component was doing its job correctly.

Three of the four in that last group share a shape worth naming: a validator rejecting a well
formed answer for a superficial reason, and the rejection being handled so gracefully that it
looked like a decision. A dropped action, a failed diagnosis and an empty plan all degrade quietly
into "the agent escalated" or "the agent did nothing", which are legitimate outcomes. Graceful
degradation and silent failure are the same code path viewed from two distances.

That is the argument for the two things this project spends the most effort on. The ledger, because
a decision that was recorded can be re-read later by someone who suspects the frame. And the
insistence in `docs/RESULTS.md` on naming what is not measured, because the number you have not
questioned is the one that will be wrong.

## Found after the freeze

### 14. The same bug as entry 1, in the one path entry 1 missed

`_open_cases` in `salvage/execute/scheduler.py` decided whether an order was already paid with
`if row["status"] == "paid": continue`. That is the exact comparison entry 1 is about, and
`_paid_by`, sitting in the same file, carries a docstring that describes the consequence:

> The agent runs over a completed simulation, so an order the customer will pay at 22:30 already
> carries a paid status at 20:10, and a policy that read the status would be reading the future:
> it would decline to act on exactly the customers who were about to come back.

Entry 1's fix was applied where the bug was found rather than everywhere the pattern occurred. The
baseline path, `_open_case_for`, has called `_paid_by` ever since. The agent path, 150 lines below
it in the same class, never did.

**It was asymmetric, which is what makes it worse than entry 1.** B1 and B2 opened cases for the
customers who were about to come back. The agent did not. Over the same world, with the same
detector and the same fault, the agent was working a smaller population than the arms it is
compared against, and not because of any policy decision.

Measured on S1 seed 1, agent arm, full run: **194 cases before the fix, 300 after.** On a capture
stopped mid-incident at 20:45 sim time, 81 against 112. The 194 matches the `cases` field in the
board fixture captured before any of this was known, which is how the two numbers were first seen
side by side.

Which direction it moved the tables is the part worth being careful about. The orders the agent
skipped are by construction the ones that were about to be paid organically, so they were recovered
either way and they landed in the agent's `organic` column. What the agent lost was the chance to
convert them earlier by link or steer. So section 3's decomposition in `docs/RESULTS.md` understates
the agent's `link` and `steer` columns and inflates its `organic` column, and the primary table
understates the agent by an unknown amount. This is the rare one that did not flatter anybody.

**How it was found, since it was not a test.** Trying to capture a dashboard fixture from a world
stopped mid-incident. The simulator writes the whole day before the detector sees any of it, so a
capture script deleted every row dated after the cutoff to make the database honest about what had
happened yet. The case count then changed, 81 to 112, which changed the eligibility counts in the
planner prompt, which missed its recorded fixture. Chasing that miss found this.

Fixed by calling `_paid_by(dict(row), now)` and adding `o.paid_at` to the select, which the query
was not fetching. Guarded by three tests: one that an order paid later still gets a case, one that
an order already paid does not, and one that greps the file for the status comparison, because the
shape of this regression is a single line and it has now happened twice.

### What entry 14 costs, and it is not small

`docs/RESULTS.md` was produced by the pre-fix code. This branch no longer reproduces it, and
re-running `salvage eval run` is not enough to make it reproduce it.

The planner prompt carries the eligibility counts, and the counts just changed, so every one of the
81 recorded planner fixtures is keyed on a prompt hash that no longer occurs. With the fix in place
and the old fixtures, the agent's planner call misses, the agent escalates on the LLM error exactly
as designed, and S1 seed 1 falls from 0.429 to 0.174 at-risk recovery with zero messages sent. That
number is a measurement of an agent with no planner. It is not a measurement of the fixed agent and
must not be reported as one.

Regenerating the results on this branch therefore needs the planner fixtures re-recorded against a
live model, which is a spend and a provenance decision rather than a command to run. Until that
happens, `docs/RESULTS.md` describes the frozen build at `e92a71c` and this branch's code does not
produce it. The freeze note at the top of `docs/BUILD_LOG.md` still describes `master`.

### 15. The at-risk figure on every incident card excluded the customers about to come back

`at_risk_amount()` in `salvage/detect/incidents.py` closed its query with `AND o.paid_at IS NULL`.
There is no time comparison in that clause, so it means "never paid, in the whole run" rather than
"not paid yet". Entry 14 again, one file over, in the number the dashboard puts in front of an
operator.

The signature already carries what it needed: the function takes `evaluated_at` and uses it to
bound which failed attempts count, then ignores it when deciding which of those orders are still
unpaid. Fixed with `AND (o.paid_at IS NULL OR o.paid_at > ?)`.

Measured on the same incident, S1 seed 1 at 20:45 sim time: **21,04,883 paise before, 25,63,193
after.** The shipped figure was 18 percent light, and light in a specific direction: it left out
the orders that were about to be paid organically, which is the same population entry 14 stopped
the agent from opening cases for.

This one touches no table in `docs/RESULTS.md`. The at-risk revenue in section 1 is accumulated by
`salvage/eval/metrics.py` over the fault-scheduled at-risk order set and never calls this function.
What it changes is the incident card, the incident list, the merchant-wide at-risk tile, and the
at-risk figure shown beside an escalation, which is to say every place a human reads it.

### 16. Three of the overview's numbers ran past the end of the world

The same query shape in three places in `salvage/api/routes_incidents.py`, all of them "as of now"
numbers with no upper bound:

- `attempts_last_hour` and the merchant success rate under it: `WHERE created_at >= ?`, so the last
  hour ran from one hour before the window to the end of the simulated world. 4,808 attempts where
  1,227 had happened.
- the volume and failures sparkline: same, so it drew 136 buckets where 96 had happened and the
  line continued past the right edge of the window the page said it was showing.
- the recovered tile: `WHERE r.route IN ('link', 'steer')` with no time clause at all, summing
  recoveries whose `recovery_routes.paid_at` had not arrived.

All three are bounded at `window_end`, which is the value the route already returns as `now`.

Unlike entries 14 and 15 this one is only wrong against a simulator. A production database has no
rows dated in the future, so an unbounded `created_at >= ?` is harmless there. It is wrong here
because the simulator writes the whole day before the detector sees any of it, and this project's
dashboard is only ever pointed at the simulator. A number that is right in a deployment nobody has
and wrong in the only one that exists is still a wrong number.

The recovered tile was not in the list of two I was asked to fix. It is in the same function as the
other two, it is the same missing clause, and leaving it would have produced a stats row where two
tiles stop at the window and the third does not. Reverting it is one clause.

**How all three were found.** By the same capture script as entry 14, which stops a world at a
chosen minute by deleting every row dated after it. Every number that changed when the future was
deleted was a number that had been reading it. That diff is the whole method, and it found four
defects: the case count, the at-risk amount, the attempts count and the sparkline. The recovered
tile came from reading the remaining query in the same function.

**And the check that they are all closed.** Capture the same world twice, once with the future
deleted and once with it left in, and diff the two payloads. Before these fixes they disagreed on
the case count, the at-risk amount, the attempts count, the success rate, the sparkline length and
the recovered tile. After them the two responses are byte identical, which is the same statement as
"no number on this page depends on data the world has not reached". `s1_detected_untrimmed.json`
was kept in `web/src/board/fixtures` as the A/B evidence and has been deleted, because it is now a
duplicate of the trimmed capture and a duplicate is the result.
