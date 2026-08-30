# Judge review

A standing review of the repository as a stranger meets it. Each round runs the same seven passes
and records what changed. Prior rounds stay, with their status, so a finding that comes back is
visible as a regression rather than as a new discovery.

The division of labour is fixed. Broken links, commands that do not run, numbers in prose that
disagree with the data, and pure colour work are fixed in place. Anything touching `salvage/`,
anything that would change a reported number, a fixture or a recording, and any rewording of a
limitation or a caveat is queued for a human, because a wrong autonomous fix to one of those costs
more than the two minutes a queued item costs to read.

---

## Round 1

Scope: the palette conversion and the static demo deployment, then the seven passes over what they
produced.

### Fixed

**F1. `--fg-3` failed WCAG AA on every ground, on every page.** Severity: high. The muted text tier
was `#69727d`, which measures 3.6 to 4.0 against the four grounds it is used on where 4.5 is the
minimum for text at these sizes. It failed on roughly four hundred elements, including on the
Overview and the Scenario Runner before the conversion, so this was not introduced by the pass. It
is now `#7f8894`, the smallest value that clears AA on the lightest ground it appears on
(`--panel-3`, where it measures 4.56) while staying visibly below `--fg-2` above it. Verified by
walking every text node on all seven routes and computing composited contrast: 165 failures on the
Overview and 149 on the Scenario Runner before, 0 on all seven routes after.

**F2. Native controls rendered light.** Severity: medium. The status filter on Incidents was a
white system select on a dark page. `color-scheme: dark` on the root fixes the select, the
scrollbars and anything else the browser draws rather than the stylesheet.

**F3. The left nav rendered white in the built demo.** Severity: high, and self-inflicted. The
chrome rules were gated on an attribute the Overview set while mounted, `html[data-surface="ops"]
nav`. Removing the gate, which was correct once every page was dark, dropped the selector below
Tailwind's `.bg-white` in specificity and the nav went white. Fixed at the source rather than by
restoring specificity: `App.tsx` and `TopBar.tsx` now carry the tokens themselves and the override
block is gone, so there is one source for each of those colours.

**F4. The narration line stopped narrating two thirds of the way through the run.** Severity: high.
The plain-English line ranked "the case is closed" above the entry the playhead was on. The
incident closes at 22:42, but the 58 refusals, the 101 held sends and every payment the next
morning happen at or after that moment, so the single most important beat on the page, a refusal
naming the rule that caused it, was never narrated at all. The line now dispatches on the current
entry first and falls back to run state, so it follows the run to the end.

**F5. Documented commands were not all correct.** Severity: low. The Vercel invocation was written
with a flag form that does not exist (`--prebuilt=false`). Corrected. `npm ci`, `npm run build` and
`npx vite preview` were each run and their behaviour is what the README now claims, including the
SPA fallback on a deep link. The `vercel` and `gh-pages` invocations are documented but not
executed here: both need an account and a network, so they are unverified and marked as such in
this entry rather than asserted as tested.

### Queued

**Q1. A zero recovered renders green.** Incidents and Incident detail show `recovered 0.00` in the
success colour. Green on a zero reads as good news about a number that is not good news. This is
pre-existing and unchanged by the conversion, and changing it alters what the page implies about a
result, so it is not a colour fix.

**Q2. The committed demo database shows a tooling failure as an agent decision.** `data/salvage.db`
carries an escalation whose reason is "planner failed: fixture provider has no response and no
recorder". On the Overview and on Escalations that renders as the agent's escalation. The Overview
does distinguish it, with a red PLANNER ERROR chip and the sentence "which is not an agent deciding
a human should take this one", which is exactly right. Escalations does not make that distinction.
Neither page is in the public demo. Touching the fixture is out of bounds.

**Q3. Escalations says "Escalated for a reason the console does not have text for."** A first-time
reader takes that as a rendering bug rather than as a missing translation. Rewording it changes what
a limitation says, so it is queued.

**Q4. Storefront is now dark.** It was on the conversion list and it is converted, but it is the one
page that is not console chrome: it simulates what a shopper sees at checkout. Making it the same
dark operational surface as the console says something about the product that a palette should not
be saying on its own. It is not in the public demo either way.

**Q5. The Escalations approve and reject controls are disabled with the text "enter the token"
repeated twice on one line.** It reads as a duplicate rendering fault. Layout, so queued.

### Passes

**1. Cold start.** Not run this round: the deployment work was still landing while the passes ran,
so a clone would have tested a tree that no longer exists. First item of round 2.

**2. Static build.** Built, served two ways, and walked. `npm run build` produces `dist` with a
`404.html` copy. Under a server with no rewrite rule every deep link 404s, which is why the copy and
`vercel.json` exist; under a server that serves `404.html` for unknown paths, which is what GitHub
Pages does, `/`, `/runner`, `/results` and an unknown path all boot the app and the router resolves
them. `vite preview` does the same. Bundle before any recording is fetched: 29.4 kB of JavaScript
and 8.0 kB of CSS, gzipped. The recordings are static assets, not modules, so the 1.5 MB one
(129 kB gzipped) is fetched when the runner opens; Recharts, 151 kB gzipped, is its own chunk that
only Results pulls in. No `/api/` request is made: see round 5, which corrects this sentence after F6 changed what is true of it.

**3. Every page, every state.** Data, empty and error states walked on all seven routes against a
live backend and against no backend. Findings F1, F2, F3, Q1, Q2, Q3 and Q5 come from this pass.

**4. Reconciliation.** Not run this round. First substantive item of round 2.

**5. Claim versus evidence.** Partial. The entry screen's three claims were checked against what the
recording contains: the fault time, the card range and the entry count are read out of the recording
rather than written into the copy, and the sentence "Where the run did not record something, the
page shows nothing rather than a guess" is enforced in three places (the health lanes, both input
confidences, and the case board's source labels). Full pass in round 2.

**6. The thirty-second test.** Run against the entry screen and the first frames. Recorded below.

**7. Freeze integrity.** Not run this round. Nothing in this round touched `salvage/`, `tests/`,
`data/results/` or any recording; the whole diff is `web/`, `README.md` and this file.

### The thirty-second test

Terms a newcomer meets before anything explains them:

- **Razorpay**, in the header tagline. A judge in Indian payments knows it. Anyone else does not,
  and the entry screen never says it is the payment processor.
- **Sim clock**, on the transport, the moment the run starts. It is the simulated world's clock and
  the page says "sim clock" without saying what a sim clock is.
- **Entry kinds**, `execute.action.refused` and the rest, on the transport line. Deliberate: they are
  the jargon tier and the plain line above carries the meaning. A newcomer reads past them.
- **Segment keys**, `card:card_bin6:411111`, in the incident panel and down the health lanes. The
  narration says "cards starting 411111" but the panels never translate the key.
- **Steer**, in the plan and in the recovered counts. The narration does not use it; the panels do,
  unexplained.
- **Baseline**, **at risk**, **gate**, **quiet hours**. Each is either explained in a footnote or
  inferable, but none is defined where it is first used.

Questions a newcomer would still have after thirty seconds:

- Is this real money and real shoppers? The entry screen says "that simulated world", which is
  accurate but easy to read past, and nothing else on the page repeats it.
- Why did it take seven minutes to notice? The page reports the number without saying whether seven
  minutes is good.
- What is a payment link, and what does the shopper actually receive?
- The narration says 58 refusals and the tiles say 232 actions taken. A newcomer cannot tell whether
  refusing a fifth of what it tried is the system working or the system failing.

None of these are rewritten here: the instruction was to report the thirty-second test, not to
rewrite copy beyond typos.

### The three questions the repo answers worst

**Is the agent actually better than just messaging everybody, or does it only look better on the
population you chose to measure?** Currently answered: honestly but late. `docs/RESULTS.md` section
1 measures the at-risk set and the agent leads on S1, S2 and S3; section 2 measures every order that
failed on the day and says plainly that the link-sending baselines beat the agent on every scenario.
That reversal is the most important fact in the document and it is in section 2, under section 1.
The README repeats section 1's table and not section 2's.

**How much of the recovery is the agent and how much would have happened anyway?** Currently
answered: in the decomposition. On S2 seed 1, 465 of 527 recoveries are organic, 42 are steer and 20
are link. `docs/RESULTS.md` section 3 gives this per scenario and B0 is exactly the organic-only
arm, so the comparison is available. But the Scenario Runner shows only link and steer, deliberately,
and a viewer of the demo alone would not learn that most recovery is organic.

**Why should I believe the numbers came from a model that was not shown the answer?** Currently
answered: well, and it is the strongest part of the repository. The recorder builds each evidence
packet through the same call the agent makes, which cannot reach the ground-truth tables; it hands
the provider a type carrying the prompt and its hash and nothing else; and `assert_blind` refuses any
prompt containing a scenario id, a seed or a cause name. The weakness is that this is only true of
the 41 diagnosis fixtures, and the 81 planner fixtures are keyed on prompt hashes that mostly no
longer occur on this branch, which `docs/RESULTS.md` and `docs/BUILD_LOG.md` now both state.

---

## Round 2

Scope: the four passes round 1 deferred, plus the demo build as a stranger meets it.

### Fixed

**F6. Results was empty in the public demo.** Severity: critical, and it defeated the point of the
demo. Results is one of the two pages a static build ships and it reads the sweep through
`/api/results`, which does not exist without a backend, so it rendered "Nothing here yet." twice. An
error panel would have been bad; an empty state is worse, because it does not read as a missing
connection, it reads as a project with no measurements. A build with no backend now answers
`/api/results` and `/api/results/{id}`, and only those, from a verbatim capture of the same routes
committed at `web/src/board/fixtures/results.api.json`. Nothing is recomputed in the browser and no
other route is intercepted. Verified: every cell of the demo's primary table matches the recompute
in pass 4 below, and the secondary whole-run table, the one where the baselines beat the agent, is
visible in the demo rather than only in the document.

**F7. The README described a Scenario Runner that no longer exists.** Severity: medium. It said to
pick a scenario, a seed and a policy and press run, which was true of the old page and is not true
of the replay. Corrected, along with a note that the page needs neither the token nor the backend.

### Queued

**Q6. `docs/PITCH.md` says the agent "loses some seeds outright" on S3; it loses one of ten.**
Recomputed: mean difference 5,840 rupees, paired standard deviation 15,993, and the agent is behind
on exactly one seed. The plural overstates how badly the agent does, so this is under-claiming and
under-claiming is not a finding. It is queued only because it is loose, and because rewording a
negative finding is not something to do unattended.

**Q7. A new committed fixture exists that was not there before.**
`web/src/board/fixtures/results.api.json`, 137 kB, a verbatim capture of two API routes reading
`data/results/`. It changes no number and transforms nothing, and F6 could not be fixed without it,
but it is a new committed artifact and worth an explicit look.

### Passes

**1. Cold start.** Clean. Cloned `ui/board` to an empty directory in `/tmp` and followed the README
with nothing from memory. `uv sync --all-extras`, `cp .env.example .env`, `uv run salvage db
migrate`, `uv run salvage agent run --scenario S1 --seed 1 --policy B1` and `uv run salvage ledger
verify` all ran with no undocumented flag and no missing prerequisite. `cd web && npm ci && npm run
build` produced `dist` including the `404.html` copy. The clone is 13 MB; `data/` is empty in it and
`db migrate` creates the database, which the README already implies and which worked.

The headless run on the clean clone reported `stream_digest=6a6e30230725aae5`, which is byte for
byte the digest `data/results/main.json` records for S1 seed 1. A fresh clone reproduces the frozen
sweep's world exactly.

**2. Static build.** Clean, and covered in round 1. Rechecked after F6: bundle is 29.5 kB of
JavaScript and 8.0 kB of CSS gzipped, plus a 9.0 kB gzipped results capture fetched only when
Results opens.

**3. Every page, every state.** Contrast rescanned over the demo build in three states, Results, the
entry screen, and the replay paused mid-run at the first refusal, including the header and the nav
this time: 0 failures. The narration at that position reads "Salvage refused to act here, because
those shoppers never agreed to be contacted."

**4. Reconciliation.** Clean. A different sample from round 1, recomputed from
`data/results/main.json` and `data/results/diagnosis.json`, never the reverse:

- Section 1, every cell of at-risk recovered revenue and at-risk messages across five scenarios and
  five arms: matches to the rupee. At-risk order counts are identical across all five arms in every
  scenario, which is the property that makes the comparison fair, and a test already asserts it.
- Section 3 decomposition for S1 and S2, recovered orders split by link, steer and organic: matches.
- README's "26 percent on 32 percent of B2's messages" for S1 and "29 percent on 31 percent" for S2:
  recomputed 26.3 and 31.8, 28.8 and 31.4.
- The S3 non-claim: 5,840 rupees on a paired standard deviation of 15,993, message share 86 percent.
  All three exact.
- The echo comparison: 16,066 more on S1, 6,081 less on S2, 15,266 less on S3, identical on S4, and
  the four summing to about minus five thousand. All exact, signs included.
- Whole-run, "baselines beat the agent by 29 to 44 percent": recomputed 36, 39, 29 and 44.
- Diagnosis accuracy over 41 incidents: rules 90.2 percent, reconciled 97.6 percent. Both exact.
- Opt-out cost "2.6 percent": 3,212 opt-outs over 125,785 messages is 2.55 percent.
- Policy violations across all 250 rows: 0, as claimed. Stream digests identical across all five
  arms in all 50 worlds: 0 mismatches.

**5. Claim versus evidence.** Clean, with Q6 the only note. The strongest claims are the ones with
the most careful hedging around them: S3 is explicitly called not a win in both PITCH and
SUBMISSION, the whole-run reversal is stated in both, and the language model's null result is stated
as a null result. No caveat present in `docs/RESULTS.md` is missing from PITCH or SUBMISSION. The
reverse is not true and does not need to be.

**6. The thirty-second test.** Unchanged from round 1; no copy was rewritten, so the same terms and
the same open questions stand.

**7. Freeze integrity.** Clean. `master` is `eaaa7f7`, which is `e92a71c` plus one commit that
changes 14 lines of `docs/BUILD_LOG.md` and nothing else, so the FROZEN note's claim that "the only
commit that follows it is this note" is accurate. Nothing in rounds 1 or 2 touched `salvage/`,
`tests/`, `data/`, `migrations/` or `scripts/`: the whole diff is `web/`, `README.md`,
`docs/BUILD_LOG.md`, `docs/RESULTS.md` and this file. The world digest check above closes it from
the other side: the simulator on this branch still produces the world the frozen sweep measured.

### Documents checked for the mechanical faults

No em dashes or en dashes in `README.md` or any file in `docs/`. Every relative link and every
backtick-quoted repository path in `README.md` and all nine documents resolves to a file that
exists. Both scans clean.

---

## Round 3

Scope: the states rounds 1 and 2 had not exercised, and a third reconciliation sample.

### Fixed

Nothing. Every finding this round is one whose fix would either strengthen a claim or reword a
limitation, and both are queued by instruction.

### Queued

**Q8. `docs/PITCH.md` says "Zero policy violations across 200 runs"; the sweep has 250.** Severity:
medium, and it is a disagreement between documents rather than only with the data. `README.md` and
`docs/SUBMISSION.md` both say 250, `data/results/main.json` has 250 rows (five scenarios by ten
seeds by five arms), and the recomputed violation count across all 250 is 0. The 200 is stale from
before the `echo` arm was added, and `docs/WHAT_BROKE.md` refers to a "200-run sweep" historically,
which is where it comes from. Correcting it to 250 would make the claim stronger, so it is queued
rather than fixed.

**Q9. `docs/PITCH.md` says "at 1,500 attempts a day, half the faults are never detected at all".**
Severity: low. `data/results/volume_sweep.json` records 4 of 10 detected at that volume, so 6 of 10
are never detected, not 5. "Half" softens a limitation, and rewording a limitation is queued by
instruction. `docs/AUDIT.md` is precise about the same sweep, so the exact figures are already in
the repository.

**Q10. On an empty database the top bar reads "SIM CLOCK 1/1/1970, 05:45:00".** Severity: low, and
invisible in the public demo, whose bar has no clock. `GET /api/overview` returns `now: 900` when
nothing has been observed, and the bar renders it as a date. A first-time viewer on a fresh install
reads 1970 as a bug. Suppressing it is a rendering change rather than a colour one, so it is queued.

### Passes

**3. Every page, every state.** The states not previously exercised, against a freshly migrated
empty database and with the kill switch on:

- Empty database: all four live pages explain themselves rather than showing a blank. Overview says
  "No attempts measured. Nothing has been observed, so there is no baseline to deviate from" and
  offers a way forward; Incidents says what would cause one to appear; Escalations and Ledger both
  read correctly. No bare zero anywhere that could be misread as a failure. Q10 is the exception.
- Kill switch on: the bar takes a red ground, "Outbound actions suspended" appears in red, and the
  control becomes "Resume outbound actions" in green. All legible on the dark surface, and the red
  is being used for exactly what the palette reserves it for.

**4. Reconciliation.** Clean apart from Q8 and Q9. A third sample, from the artifacts neither
earlier round touched:

- `docs/AUDIT.md` F5's paired statistics: S1 mean +46,104 with t=2.92, S2 +26,810 with t=1.99, S3
  +5,840 with sd 15,993 and t=1.15. All four exact, and its "the agent loses seeds outright on all
  three scenarios, one to two of ten each" recomputes as 1, 2 and 1 of ten. AUDIT is the most
  precise document in the repository on its own weakest result.
- `data/results/volume_sweep.json`: the boundary string it stores matches its own rows, and PITCH's
  "somewhere between 5,000 and 12,000 attempts a day" matches (5 of 10 within fifteen minutes at
  5,000, 10 of 10 at 12,000).
- `data/results/offpeak.json`: 20 rows, none opened an incident, so AUDIT's "zero of twenty trough
  faults detected" is exact.
- `data/results/fault_injection.json`: 45 attempts, 45 refused, no unrefused, matching README,
  PITCH and SUBMISSION.

---

## Round 4

Scope: the checks that prove the branch is shippable rather than only correct.

### Fixed

**F8. The branch failed its own CI.** Severity: high. `.github/workflows/ci.yml` runs `uv run ruff
check .`, and `scripts/capture_board_fixture.py` had a 106 character line against a 100 character
limit. The file exists only on `ui/board`, added by an earlier commit on this branch, so `master` is
unaffected and its FROZEN claim of "ruff clean" still holds. `ruff format` could not fix it, because
it will not split a string, so the f-string is split across two adjacent literals; the concatenation
is byte-identical to the original, which is asserted rather than assumed. `ruff check` and `ruff
format --check` are both clean now.

**F9. "PLAN 1 actions" on the lifecycle track.** Severity: low, a typo. Pluralised.

### Queued

Nothing new.

### Passes

**1. Cold start.** Unchanged from round 2 and rerun implicitly: the fresh clone was rebuilt after
the round 2 changes and produced the same output.

**7. Freeze integrity.** Clean. 496 tests pass, ruff clean, format clean. The suite appeared to fail
with 10 failures and 99 errors partway through this round, all `sqlite3.OperationalError: disk I/O
error`. That was not a defect: the earlier scenario sweep and several full test runs had left 3.8 GB
of simulated worlds in `/tmp`, which is a 5.5 GB tmpfs, and SQLite reports exhaustion that way. With
the temporary databases removed the suite passes in full. Recorded because a reviewer who runs the
suite after a sweep will hit the same thing and it looks alarming.

`master` remains `e92a71c` plus a documentation-only commit. The only file outside `web/`, `README.md`
and `docs/` that any round has touched is `scripts/capture_board_fixture.py`, which is not on a
measured path: it writes a board fixture and no number in `docs/RESULTS.md` comes from it, which its
own docstring states.

**2 and 3. Static build, every page.** The second recording checked in the built demo. Switching to
S4 seed 0 does not bring the entry screen back, the narration follows it correctly in plain English
("bank transfers are failing", "a setting on the shop's own payment account is wrong"), and the
lifecycle track puts ESCALATE at "current stage" with RECOVER "not reached". Escalation renders as
terminal, as it must.

One thing on that track is worth a reader knowing rather than fixing: GATE reads "no rules
evaluated" while EXECUTE reads "1 executed". That is accurate. `ESCALATE_HUMAN` is an
incident-level action the matrix always allows, so the policy engine records an empty ladder for it,
and the gate panel says so in as many words.

---

## Round 5

Scope: all seven passes over the state rounds 1 to 4 produced, from a clean clone.

### Fixed

**F10. A sentence in this document's round 1 entry stopped being true.** Severity: low, and it is
bookkeeping about bookkeeping. Round 1 recorded "No `/api/` string survives in the demo bundle",
which was true when it was written. F6 in round 2 made the demo answer `/api/results` from a
committed capture, so the string is in the bundle now as a path constant that never reaches the
network. Corrected in place, with a pointer here, rather than deleted: a review log that quietly
edits its own history is not a review log.

### Queued

Nothing new. Q1 through Q10 stand.

### Passes

**1. Cold start.** Clean, from a second fresh clone containing every commit. `uv sync`, `ruff check
.` (which is what CI runs, and which round 4 fixed), `db migrate`, the headless demo and `ledger
verify` all ran. The headless run again reported `stream_digest=6a6e30230725aae5`, matching
`data/results/main.json` for S1 seed 1, and the chain verified at 2,562 entries. `npm ci` and `npm
run build` produced `dist` with `404.html`.

**2. Static build.** Clean. Served the clean clone's build with a Pages-like 404 fallback: `/`,
`/runner`, `/results` and an unknown path all resolve. Network trace on the demo shows exactly one
data request, `/assets/results.api-*.json`, and no `/api/` call at all. The only third-party request
is Google Fonts, which every font token has a system fallback for, so the page is readable if it is
blocked.

**3. Every page, every state.** Contrast rescanned on the clean clone's build across Results, the
entry screen and the replay paused at the first refusal, including header and nav: 0 failures in all
three. F9's fix is confirmed in the built artifact: the track reads "PLAN 3 actions" on S2 and
"1 action" on S4.

**4. Reconciliation.** Clean. A fourth sample, from the two artifacts no earlier round had opened:

- `data/results/escalation_fix.json` against PITCH's escalation-to-fix paragraph: at a two hour
  response the agent recovers 2,67,435.23 rupees and at fifteen minutes 2,77,080.14, against B2's
  1,83,115.32, on zero messages. PITCH says "between 2,67,435 and 2,77,080 against B2's 1,83,115"
  and "46 percent ahead" for the slowest. Recomputed: 46 percent at two hours, rising to 51. Exact,
  and the claim is pinned to the least flattering end of its own range.
- The same file's `beyond_the_fault` rows: at a 180 minute response the agent is back to the no-fix
  figure exactly, which is what PITCH's "past the fault's own 180 minute duration the fix is worth
  exactly nothing" says.
- `data/results/steer_sensitivity.json`: `shipped_value` is 0.55 and the sweep runs 0.25 to 0.65,
  matching AUDIT's description of the assumed constant and its sweep.

**5. Claim versus evidence.** Clean. Nothing found beyond Q8 and Q9, both from round 3 and both
still queued.

**6. The thirty-second test.** Unchanged. No copy was rewritten in any round, so the terms and open
questions recorded in round 1 stand exactly as written.

**7. Freeze integrity.** Clean. 496 tests pass, `ruff check` and `ruff format --check` both clean on
a fresh clone. `master` is untouched at `e92a71c` plus its documentation commit.

---

## Round 6

Scope: the two areas no earlier round had opened, the remaining sweep artifacts and the four
specification documents.

### Fixed

Nothing.

### Queued

**Q11. `docs/04_FRONTEND_SPEC.md` section 4.7 specifies a Scenario Runner that no longer exists.**
Severity: medium. It specifies a form with scenario, seed, policy and speed, Run and Stop buttons
behind the token, a live log of the last 50 server-sent events, and a summary card afterwards. The
page is now a replay of a committed recording and has none of those. A judge comparing the spec to
the app finds a page that does not match its own contract.

Resolving it means either editing the specification, which changes a contract, or adding a note to
it, and both are a decision rather than a correction. `docs/BUILD_LOG.md` records why the page
changed and `README.md` describes what it now is, so the reasoning is on the record; it is only
section 4.7 that still describes the old page. Two smaller instances of the same thing sit beside
it: section 3's route table lists `/api/sim/run`, `/api/sim/stop` and `/api/sim/status` as the
Scenario Runner's routes, and section 4.1 says the Overview's empty state links to it to run a
scenario, which it still does but that link now leads to a replay.

### Passes

**4. Reconciliation.** Clean. A fifth sample, the artifacts nothing had opened:

- All 250 rows of the five per-scenario shards checked cell by cell against `main.json`: 0
  mismatches, so the shards and the aggregate are the same run.
- `data/results/sensitivity.json`: the B1-versus-B0 nudge multiplier sweep runs 0.5 to 1.5, which is
  what `docs/AUDIT.md` says of it, including AUDIT's own criticism that it covers only B1 against B0
  on five seeds.
- `record_pass.json` and `echo_record.json`: the per-world digests are identical to each other and
  to `main.json` for the same scenario and seed, which is the property that makes the echo arm a
  control rather than a different experiment.

**5. Claim versus evidence.** Clean apart from Q11, which is a specification rather than a claim.
Checked specifically whether the demo drops a caveat that `docs/RESULTS.md` carries: it does not.
The demo's Results page shows the secondary whole-run table, the one where the link-sending
baselines beat the agent, with its explanatory line intact, so the least flattering result in the
project is visible to anyone who opens the second page of the demo.

**1, 2, 3, 6 and 7.** Not rerun. Nothing has changed since round 5 except this file and the
documents it names, and rerunning a build and a contrast sweep against an unchanged tree would be
manufacturing evidence of work rather than checking anything.

---

## Round 7

Scope: all seven passes, run in full against a third clean clone.

### Fixed

Nothing.

### Queued

Nothing new.

### Passes

**1. Cold start.** Clean. Third clean clone, README followed with nothing from memory. `uv sync`,
`ruff check .`, `ruff format --check .`, `db migrate`, a scenario run and `ledger verify` all ran.

This round ran the scenario the demo recording came from rather than the one the README names, and
it produced the recording: 508 entries, head hash `9bc5ac71bd95`, identical to
`web/src/board/fixtures/s2_seed1.run.json`. The committed recording is not just a file that happens
to be in the repository; it regenerates byte for byte from a clean clone, and the page that replays
it can therefore be checked against the code rather than taken on trust.

**2. Static build.** Clean, and reproducible. The builds from two independent clean clones hash
identically over every file in `dist`.

**3. Every page, every state.** Not rerun in the browser. The built output is byte-identical to the
one round 5 walked, so the contrast and behaviour results carry over exactly; rerunning them would
have measured the same bytes twice.

**4. Reconciliation.** Clean. A sixth sample, the last artifact nothing had opened:
`docs/results_by_run.csv`, 250 rows and 30 columns, checked cell by cell against
`data/results/main.json`. 4,700 numeric cells compared, 0 mismatches, 0 rows in the CSV that are not
in the artifact.

**5. Claim versus evidence.** Clean. Nothing new beyond Q8, Q9 and Q11.

**6. The thirty-second test.** Unchanged. No copy has been rewritten in any round.

**7. Freeze integrity.** Clean. 496 tests pass, ruff and format clean, `master` untouched.

### Stopping

Round 7 produced no new findings, which is the stopping condition. Eleven items are queued and
nothing else is outstanding.

---

## The queue, as it stands

Nothing in this list has been touched. Each is either a claim, a limitation's wording, a layout
decision, or something that would make the agent look better, and all four are yours by
instruction.

| | Severity | What |
|---|---|---|
| Q1 | low | `recovered 0.00` renders in the success colour on Incidents and Incident detail. |
| Q2 | medium | `data/salvage.db` shows a fixture-miss as an agent escalation; the Overview labels it a planner error, Escalations does not. |
| Q3 | low | Escalations says "Escalated for a reason the console does not have text for", which reads as a rendering bug. |
| Q4 | low | Storefront is now on the console's dark surface, and it is the one page that is a shopper's view rather than an operator's. |
| Q5 | low | Escalations shows "enter the token" twice on one line beside the disabled approve and reject controls. |
| Q6 | low | `docs/PITCH.md` says the agent "loses some seeds outright" on S3; it loses one of ten. Under-claiming. |
| ~~Q7~~ | resolved | Capture inspected and accepted. Verified verbatim against the live routes, and the demo's Results page now says on its face that the figures are a captured snapshot and names the run. |
| ~~Q8~~ | resolved | Fixed. PITCH now reads "across all 250 runs", matching README and SUBMISSION and the artifact. |
| Q9 | low | `docs/PITCH.md` says "half the faults are never detected" at 1,500 attempts a day; the sweep records 6 of 10. |
| Q10 | low | On an empty database the top bar renders the epoch as "1/1/1970". Not visible in the public demo. |
| ~~Q11~~ | resolved | Spec left as specified. A document-level note records that it describes the original design and that 4.7 was superseded on `ui/board`. |

## The three questions a sharp payments engineer would ask, and where they stand

Unchanged in substance from round 1, with what the rounds since have added.

**Is the agent actually better than messaging everybody, or does it only look better on the
population you chose?** The honest answer is in the repository and it is not flattering: on the
at-risk set the agent leads on S1, S2 and S3; on every order that failed that day the link-sending
baselines beat it on every scenario, by 29 to 44 percent, recomputed this round. Both are stated.
The weakness is placement, not honesty: `README.md` reproduces the flattering table and not the
other one, and a reader who stops at the README does not learn the reversal exists. The public demo
is better than the README here, because its Results page shows both tables and the reversal is on
the same screen.

**How much of the recovery is the agent and how much would have happened anyway?** Answered
precisely, in section 3 and in the B0 arm which is organic-only by construction. On S2 seed 1, 465
of 527 recoveries are organic against 42 steer and 20 link. The Scenario Runner deliberately counts
only link and steer, which is the right choice for a page about what the agent did, but it means a
viewer of the demo alone would not learn that most recovery happens without it.

**Why should I believe the model was not shown the answer?** This is the strongest part of the
repository. The recorder builds each evidence packet through the same call the agent makes, which
cannot reach the ground-truth tables; it hands the provider a type carrying the prompt and its hash
and nothing else; and `assert_blind` refuses any prompt containing a scenario id, a seed or a cause
name. The limit is that this covers the 41 diagnosis fixtures, and the 81 planner fixtures are keyed
on prompt hashes that mostly no longer occur on this branch, four of twenty scenario and seed pairs
still hitting. `docs/RESULTS.md`, `docs/BUILD_LOG.md` and `docs/WHAT_BROKE.md` all state this now.

---

## Directed actions, after round 7

Three items handled on instruction rather than as a review round.

**Q8, fixed.** `data/results/main.json` holds 250 rows: five scenarios by ten seeds by five policy
arms, 250 distinct combinations, no duplicates, and 0 policy violations summed across all of them.
`docs/PITCH.md` now reads "Zero policy violations across all 250 runs", identical to `README.md`
and `docs/SUBMISSION.md`. The 200 was stale from before the `echo` arm made it five arms.

Every other count shared by those three files was checked for the same drift and agrees: 41
incidents, 37 of 41 correct on rules alone, 45 fault injection attempts all refused, 10 seeds. The
neighbouring claims in the sentence that changed were recomputed rather than assumed: zero incidents
across all 50 S0 rows, and per-scenario detection means of 5.4, 8.6, 7.0 and 9.5 minutes, which is
the "5 to 10 simulated minutes" the line claims.

Remaining "200 run" references are historical and correct in context: `docs/WHAT_BROKE.md` twice and
`docs/BUILD_LOG.md` twice, all describing the four-arm sweep as it was at the time. One is not
historical, `docs/AUDIT.md` line 211, "neither breaker branch fires anywhere in the 200-run sweep",
which reads as a live reference to the current artifact. AUDIT is outside the three files named, so
it is untouched and noted here.

**Q7, inspected and accepted with a visible notice.** The capture is
`web/src/board/fixtures/results.api.json`, 137 kB, produced by the command in `docs/BUILD_LOG.md`,
which calls `GET /api/results` and then `GET /api/results/{id}` for every run the first call lists
and writes them under those keys. It adds `_note`, `captured_at` and `git_rev` and transforms
nothing else.

Verified rather than asserted: with the API running against `data/results/`, all nine responses in
the capture, the listing plus eight runs, are deep-equal to what the routes return today. No edits.

`web/src/pages/Results.tsx` now renders a notice above the tables in builds with no backend, saying
the figures are a captured snapshot of a real evaluation run, naming the run id the tables are keyed
on, and stating that nothing on the page is computed in the browser. It does not appear in the full
console, where the page genuinely is live. Confirmed present in the demo build and absent in the dev
build.

**Q11, recorded rather than retrofitted.** Section 4.7 is unchanged. There was no existing
divergence line to extend, in that document or any other, so a document-level note was added under
the version line: 13 insertions, 0 deletions, nothing removed anywhere in the file. It states that
the document records what was specified rather than what was built, that the Scenario Runner was
rebuilt on `ui/board` after the spec was written and why, and that section 3's route table and
section 4.1's empty-state link are historical for the same reason.

### One new item, not acted on

**Q12. `docs/04_FRONTEND_SPEC.md` section 8 lists "Dark mode, theming" as out of scope.** Severity:
low. The whole console is now on a dark surface. This is the same class as Q11 and it is in the same
document, but it was not part of the instruction and the note added above deliberately does not
claim to be an exhaustive list of divergences. Flagged so the note can be extended if you want it to
cover this too.

