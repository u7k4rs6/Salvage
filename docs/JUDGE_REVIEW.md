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
only Results pulls in. No `/api/` string survives in the demo bundle.

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

