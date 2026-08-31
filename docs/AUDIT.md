# Adversarial audit

Read-only audit of the repository as submitted. Everything below was verified against source and
data in this checkout; commands run were read-only or wrote only to scratch databases outside the
repo. Where a claim required running the agent, the run used the checked-in fixtures and a scratch
DB, and is labelled as a probe.

The single most important sentence first: **the strongest result in the repo is weaker than it is
presented.** The agent's headline win is real on S1 and S2, not statistically supportable on S3,
rests heavily on one assumed constant (a 55 percent steer conversion) that no sensitivity sweep
ever touches, and coexists with a whole-run comparison, shown in RESULTS section 2 but never
spoken aloud in the pitch, in which B1 and B2 beat the agent on every scenario by 35 to 45
percent. None of the numbers are fabricated; every one I recomputed reconciles. The problem is
selection and emphasis, not arithmetic.

## Verdicts on the eight claims

### 1. Identical worlds: VERIFIED

`salvage/sim/rng.py` derives every stream from (seed, name) or (seed, name, order_index) via
sha256, so a substream's sequence cannot depend on what any other substream consumed. World draws
(customers, arrivals, attempts, organic response) are simulator-side and pre-policy. Policy-side
draws are `intervention:{nudge}` (response.py, keyed per order and nudge so all arms resolve the
same nudge against the same value), `steer` (scheduler.py:1141, per order), and `repair`
(response.py REPAIR_STREAM, per order). No policy code writes payment_attempts: the only callers
of `upsert_attempts_batch` are in `sim/runner.py` (flush, line 526). The digest
(`sim/runner.py:118`) is computed at simulation end, before any policy runs, over
v_payment_attempts ordered by (created_at, id). Empirically: all 200 rows in
docs/results_by_run.csv show exactly one digest per (scenario, seed) across the four arms, and S0
agent equals B0 to the paise on every seed. One honest caveat the docs already carry: the recorded
stream includes organic retries that logically would not happen in a world where a link already
paid the order; attribution by earliest paid_at handles the money, but the attempt rows remain.

### 2. At-risk order set identical across arms: VERIFIED

`at_risk_orders` (eval/baselines.py:213) is computed from FaultWindow objects built in
`eval/agent_run.py` from `sim.scheduled_faults`, the world's schedule, never from incidents, so
detection latency cannot move the denominator for any arm. The escalation-fix mechanism mutates
only the runner's private copy of the fault list (`scheduler._world_faults`); the windows used by
`measure_run` are rebuilt from the schedule afterwards and are untouched.
tests/unit/test_comparability.py asserts the sets themselves (not counts) are identical across
all four arms. Note the semantics on S3: the selector is empty, so every first-failure inside the
window is "at risk", including background failures that would have failed anyway. Identical
across arms, but it stretches what "the fault put at risk" means for the gateway scenario.

### 3. Blind fixture recording: PARTIALLY VERIFIED

The blindness is genuine. `PromptForRecording` (eval/run.py) carries prompt and hash only, the
packet is built through the same `build_for_incident` the agent uses (v_* views, cannot reach
sim_truth_*), `assert_blind` rejects scenario ids, seeds and cause names in the user prompt, the
rules classifier is not run while recording, and
tests/unit/test_db_schema.py::test_only_the_evaluation_runner_reads_ground_truth walks the source
tree. The 46 self-authored M2 fixtures are gone and nothing descends from them.

What the claim oversells is difficulty, not blindness. The simulator generates each scenario's
errors from a cause-specific profile (params.yaml scenarios block) whose vocabulary mirrors the
taxonomy text in the system prompt: S4 emits source=business reasons and additionally sets
`merchant_config_changed_recently: True`, which is close to a label bit; the rules classifier
scores 1.00 on S4 and 0.90 overall using regex-grade logic. On a six-class problem this separable,
40 of 41 from a competent model is close to the expected outcome, not a surprise. The measurement
shows Gemini can read a distribution table whose generative process was written from the same
taxonomy it was taught. It does not show real-world diagnostic skill, where error fields are
noisy, missing and gateway-dependent. RESULTS' "one model on one day" caveat covers stability,
not this.

### 4. Baselines are honest: VERIFIED

B1 and B2 differ from the agent only via profile flags (baselines.py:31-92): no matrix, no
defer-while-degraded, no steer, fixed nudge offsets. Same executor, same gates otherwise (the
kill-switch run in BUILD_LOG shows baselines refusing on consent, quiet hours, hard declines),
same channel, same per-order intervention draws, and `_rail_broken_at` reads the world fault
schedule, not detector incidents, precisely so a baseline's outcome cannot depend on detection.
Baselines get the 2.2 post-recovery multiplier symmetrically when their nudge lands after the
fault ends. The synthetic baseline incident is excluded from incident counts. One design note a
panelist will raise, not an implementation asymmetry: B1 sends at offset 0, which on a 90 to 180
minute fault maximises its exposure to the 0.3 still-failing multiplier and the 0.12 opt-out
draw. B2 at 1h and 6h partially escapes it. The blunt baseline most favourable to the blunt
strategy (send at 3 to 6 hours only) is not in the set.

### 5. Response model neutrality: PARTIALLY VERIFIED, with the sharpest finding of the audit

Probe run (scratch DBs, S1 seed 1, agent arm): recorded fixtures recover 165,507 rupees at-risk
with 89 messages; a provider that always answers a confident wrong cause (customer_side)
recovers 74,648 with 0 messages, exactly equal to the no-model run. So no, a random cause
classifier cannot score close to the real agent; the reconciliation gate (disagree, confidence
capped at 0.5, escalate) does real work, and the measurement is not structurally rigged in that
direction.

But the same reconciliation logic (diagnose/reconcile.py) implies something the pitch obscures:
the LLM's measured revenue contribution over a stub that simply co-signs the rules is zero. In
every incident where the model beats the rules, the rules said `unknown` (all four misses in
data/results/diagnosis.json), which means disagreement, confidence at most 0.5, escalate, no
action. In every incident where the agent acts, the rules were already right and the model
agreed. A hypothetical model that echoed the rules verdict would produce identical action
decisions in all 41 incidents (unknown plus agreement clears confidence but the matrix allows
nothing but escalation for unknown, menu.py:213). The 7.4-point accuracy edge (0.976 vs 0.902)
converts to zero rupees in this sweep. The pitch's "the diagnosis ablation says where that comes
from" is therefore wrong as a causal claim: the revenue comes from the rules classifier, the
matrix, steering and timing; the LLM's role is unlocking the confidence gate that the project
itself chose to key on model agreement.

Separately: the win's sensitivity to the response-model constants is unmeasured where it matters.
See finding 2.

### 6. Policy engine completeness: PARTIALLY VERIFIED

All PRD section 9 rules exist as gates in decide/policy.py and are exercised: single open link,
2-per-incident and 3-per-7-day caps, consent, opt-out, quiet hours with queue-to-09:00, defer
while degraded (agent only, by design), hard declines, 72h TTL, kill switch, amount
representability (no amount field in the schema), circuit breaker with both branches. Unit and
property tests can fail each; the kill-switch and injection suites exercise refusal paths.

Two gaps. First, PRD 9 says a circuit trip should "pause that incident and escalate". The trip
refuses actions (global.circuit_breaker_closed) but `_refuse` escalates only on matrix refusals
(scheduler.py, `refused_for_matrix`), so a tripped breaker pauses silently and no human is told.
Second, neither breaker branch ever fires in the shipped sweep (the simulated gateway never
fails, and post-M3 the pay-rate branch is measured only over sends older than 6h); both are
covered by unit tests with fabricated rows, which is legitimate, but the sweep exercises the
breaker zero times, so its interaction with a live run is untested end to end.

### 7. Ledger claims: VERIFIED, with one framing caveat

Single write path: the only `INSERT INTO ledger` in the tree is inside `Ledger.append`
(ledger.py:154), which runs BEGIN IMMEDIATE, reads the head, hashes, inserts. The stream
commitment is real: sim.run.finished carries stream_digest, stream_attempts and the field list
(runner.py:300-311), and scripts/verify_ledger.py re-verifies exports offline. PII: the schema
has no name, phone or email anywhere; customers carry a salted ref_hash; comms store body_hash
only; the UPI handle stored is the suffix, not the full VPA. Caveat: `salvage demo reset` deletes
ledger rows unless --keep-ledger is passed. Append-only is a property of the write path, not of
the file; the audit trail survives tampering detection, not deletion. That is disclosed but a
panelist will ask.

### 8. Contract tests: PARTIALLY VERIFIED

The fixtures in tests/unit/test_normalize.py and test_webhooks.py are hand-transcribed from the
official docs with URLs and a fetch date, and the ids and field sets match Razorpay's published
samples (pay_DEAU825sJlCbGa, the payments entity card block). They were not fetched
mechanically, and the same author wrote the normaliser, so a shared transcription error would
pass. Mitigating: the simulator emits entities through the same normaliser used for webhooks, so
there is one mapping, not two. The check that would break the circularity, the real test-mode
end-to-end run, has never been executed (RESULTS section 12 is an empty template). Until it runs,
"verified against official docs" means "matches what a careful human copied from the docs."

## Findings, ranked by damage to a reported number

### F1. The pitch omits the whole-run loss and misstates the S3 message ratio

RESULTS section 2 shows B1 and B2 beating the agent on whole-run recovered revenue in every
scenario (S1: agent 11.03 lakh, B2 17.30 lakh; recomputed from the CSV, it reconciles). The pitch
cites the whole-run comparison only where it favours the agent ("on S1 the agent sends 90
messages where B2 sends 1,296") and never states that the baselines recover 35 to 45 percent more
whole-run money. The pitch and README also claim the agent sends "between a third and a half as
many messages" across S1 to S3; on the at-risk scoping the table sits above, S3 is 422 against
492, which is 86 percent. The ratio claim mixes scopings to the agent's advantage.
Invalidates: the pitch's implicit claim that the agent dominates. Smallest honest fix: one
sentence in the pitch stating the whole-run numbers and why the at-risk scoping is primary, and
correct the ratio sentence to name S1 and S2 only.

### F2. The headline rests on an unswept constant, and the sensitivity section pretends otherwise

Decomposition (recomputed from the CSV): on S1 the agent's at-risk recoveries are 71 steer, 17.5
link, 36.4 organic; on S2, 37 steer, 9.4 link, 20.4 organic. The majority of the winning margin
on both scenarios flows through the steer route, which pays out at a flat assumed 0.55
(params.yaml, "live checkout steer during the failing session"), costs zero messages, and is
exclusive to the agent by design. `sensitivity_sweep` (eval/sweep.py:490) scales only the two
nudge multipliers, only for B1 versus B0, on 5 seeds, and data/results/sensitivity.json predates
the measured agent arm (Aug 25 02:28). The limitations section still says "the response-model
multipliers are judgement, which is what section 9 exists to quantify", which is now misleading:
section 9 quantifies a comparison the headline no longer depends on and never touches the one
parameter the headline depends on most. The adversarial set likewise still has no agent column,
despite M3's own note that the set exists for agent-versus-B1.
Invalidates: the robustness implied for the primary table. Smallest honest fix: rerun sensitivity
with the agent included, sweeping steer 0.2 to 0.55 and the 2.2 multiplier, and report the band;
until then, a limitation naming steer as unswept.

### F3. The LLM's accuracy edge buys zero revenue, and the pitch implies it buys the win

Established analytically from reconcile.py and menu.py and consistent with diagnosis.json: all
four rules misses are `unknown`; disagreement escalates; unknown-plus-agreement is matrix-blocked.
A rules-echo stub would make identical action decisions in all 41 incidents. The wrong-cause
probe confirms the gate works (wrong cause collapses to B0 exactly), so the system is defensible;
the sentence "the diagnosis ablation says where that comes from" is not.
Invalidates: the causal story connecting 0.976 to the revenue table. Smallest honest fix: state
that the model's measured role is co-signing the rules, and that its accuracy edge shows up as
three correctly-labelled escalation tickets, not as money.

### F4. The ablation's difficulty is manufactured by the instrument

Claim 3 verdict, second half. The simulator's error profiles are written from the same taxonomy
the prompt teaches, and S4 carries a near-label flag. 0.976 on this task is reading
comprehension. Nothing was leaked and nothing was tuned, but presenting the number next to
"recorded blind" invites the reader to hear "hard problem, solved" when the honest gloss is
"synthetic problem, separable by construction; the rules get 0.90 with regexes."
Invalidates: any generalisation from the LLM column. Smallest honest fix: a sentence in RESULTS
section 6 saying the classes are separable by construction and the rules-only column is the
difficulty floor.

### F5. S3's at-risk edge is inside the noise

Paired per-seed differences, agent minus B2, at-risk revenue: S1 mean +46,104 rupees (t=2.92),
S2 +26,810 (t=1.99), S3 +5,840 with sd 15,993 (t=1.15; the agent loses seeds outright on all
three scenarios, one to two of ten each). README's "wins S1 to S3 on both axes at once" and the
pitch's equivalent are not supportable for S3 revenue, and the primary table reports means with
no spread (the whole-run table has spreads; the primary does not).
Invalidates: the S3 cell of the headline claim. Smallest honest fix: add spread or paired-diff
columns to the primary table and downgrade S3 to "ties B2 on revenue with fewer messages."

### F6. Circuit breaker trip does not escalate

PRD 9: "pause that incident and escalate." Code: pause yes, escalate no (only matrix refusals
reach `_escalate`). Also neither breaker branch fires anywhere in the 200-run sweep. That figure is
the sweep as it stood when this audit was written, four policy arms across five scenarios and ten
seeds; `data/results/main.json` is now 250 runs across five arms. The claim was not re-checked
against the larger sweep, because no artifact records a breaker event and re-checking means
re-running the sweep, so read it as of the audit rather than of the current artifact.
Invalidates: the "every stopping rule enforced" sentence, narrowly. Smallest honest fix: escalate
on trip, one test.

### F7. Stale artifacts presented beside fresh ones

sensitivity.json (02:28), offpeak.json (01:52) and volume_sweep.json (01:56) were produced on
Aug 25 before the planner fixes and the measured agent arm; main.json and escalation_fix.json are
from the current code. RESULTS renders them in one document with no generation stamp per section.
For detection-only tables the staleness is likely harmless; for the sensitivity and adversarial
sections it is exactly where the missing agent column hides.
Smallest honest fix: regenerate all three on current code, or stamp each section with its source
artifact's date.

### F8. The escalation-fix crossover leans on two disclosed but compounding assumptions

Both are stated in RESULTS (asymmetry: only the agent can be repaired; understatement: the
attempt stream is not rewritten), and `never` reproduces M4 to the paise, which I verified
against the committed CSV. But the headline sentence "46 percent ahead on zero messages" combines
the agent-only repair with the generous fault-matching rule (`_fault_answers_segment`, "not
contradicted" rather than "named"), and no counterfactual exists for "merchant notices the dead
method without Salvage at T plus something." The curve measures escalation-with-cause against a
world where nobody else ever looks at a dashboard.
Smallest honest fix: a B0-plus-fix row at a slower T, representing a merchant who notices on
their own, so the reader can subtract.

### F9. Payments realism items a payments engineer will flag

- Quiet hours 21:00 to 09:00; TRAI's commercial window ends at 21:00 but begins at 10:00. The
  repo disclaims TRAI compliance, but the number reads as a near-miss transcription.
- A recovery link pays between 5 minutes and 6 hours after send with a single flat draw; no
  link-open, no partial funnel, no expiry-before-TTL behaviour.
- A steer pays 4 minutes after the original failure, in-session, at 55 percent for any customer
  with an alt method; real checkout-retry conversion in a degraded session is not close to that
  for most merchants.
- Messages are free except a 2.6 percent opt-out draw (recomputed; matches). No DLT registration,
  sender reputation, complaint or unsubscribe-list cost. This flatters the baselines more than
  the agent, so the direction is disclosed correctly, but it also means the opt-out numbers carry
  no consequences inside the model.
- No refunds, chargebacks, settlement, or webhook latency anywhere.

## Checked and fine

- RNG isolation as designed; no policy-side draw from a sequential world stream (grep of
  execute/, decide/, eval/ shows only the per-order steer draw).
- Stream digests identical across arms in all 50 worlds; S0 agent equals B0 per seed to the paise.
- At-risk set from the world schedule; identity asserted on the sets themselves in tests.
- mark_order_paid takes MIN of timestamps; first-past-the-post attribution consistent.
- No path writes payment_attempts outside the simulator; webhook replay is dev-only and not in
  the sweep.
- Ledger: one write path, IMMEDIATE transaction, genesis pinned, offline verifier, digest
  commitment present in sim.run.finished; export slice by ref_id correctly documented as not
  independently verifiable.
- No PII columns anywhere; ref_hash salted; comms store body hashes; fixtures contain no keys or
  PII (scanned); the Gemini key is absent from the entire git history.
- Numbers recomputed and reconciled: primary table cells (all five scenarios), whole-run means,
  message and opt-out tables, 2.6 percent opt-out rate, 1,436 messages, the 46 percent crossover,
  0.976 equals 40 of 41, never-row additivity to the paise.
- Fixture provenance line is read from the fixture files and now counts diagnosis and planner
  fixtures separately.
- A sweep fails loudly on an unfilled fixture miss; a wrong-cause model cannot impersonate the
  agent (probe above).
- No em or en dashes in the shipped documents; doc-claim tests enforce several of the above.

## Questions a hostile panelist will ask, with the current best honest answer

1. "Whole-run, B1 beats your agent by roughly six lakh per run. The merchant's bank account sees
   whole-run. Why not just run B1?" Honest answer: the two are not exclusive; the agent acts on
   incidents and B1's background campaign acts on everything else, and the right product is
   probably both, with the agent suppressing the campaign inside incident scope (S4, S0). The
   repo never measured that hybrid. There is no good answer in the data today.
2. "Your S1 and S2 margins are mostly steer at an assumed 55 percent conversion. Where does 0.55
   come from and what happens at 0.2?" Honest answer: it is asserted in the architecture document
   and swept nowhere. No good answer today.
3. "Would a rules-only agent with the confidence set to 0.7 instead of 0.5 match your LLM agent?"
   Honest answer: on this sweep, yes, action for action, except it would also act on the four
   `unknown` incidents' escalation path identically. The LLM's measured value is a co-signature
   and three correctly-labelled tickets.
4. "What does this do overnight, or for a merchant a tenth this size?" Honest answer: nothing;
   zero of twenty trough faults detected, boundary between 5,000 and 12,000 attempts per day, and
   it is documented prominently. This one has a good answer because the repo measured it.
5. "Have you ever created a real Payment Link?" Honest answer: no. The script exists and refuses
   to run without credentials; section 12 is an empty template.
6. "Your ledger can be deleted by your own reset command. What does append-only mean?" Honest
   answer: tamper-evidence within a surviving file, not tamper-proofing; deletion is loud (chain
   restarts at genesis) but possible.

## Three days, if the goal is that every number survives scrutiny

1. Day 1: sensitivity that matters. Rerun the sensitivity and adversarial sweeps on current code
   with the agent arm included; add steer probability (0.2 to 0.55) and the 2.2 multiplier as
   swept axes; report agent-minus-B2 bands on the at-risk set. This either defends the headline
   or resizes it, and nothing else matters until it is done.
2. Day 2 morning: honesty edits. Whole-run loss stated in the pitch; S3 downgraded; ratio
   sentence corrected; spread columns in the primary table; F3's causal sentence rewritten; F4's
   separability sentence added to section 6.
3. Day 2 afternoon: the rules-echo arm. One sweep with the LLM replaced by a stub that returns
   the rules verdict at 0.7 confidence. Publishing that the echo matches the agent is
   uncomfortable and is exactly the kind of number that buys credibility for everything else.
4. Day 3 morning: circuit-trip escalation plus test; regenerate offpeak and volume artifacts on
   current code; stamp artifact dates into RESULTS sections.
5. Day 3 afternoon: the hybrid arm (agent plus background B1 outside incident scope), because it
   is the answer to the panel's best question, and the real test-mode end-to-end run if
   credentials can be obtained; it converts claim 8 from transcription to verification.
