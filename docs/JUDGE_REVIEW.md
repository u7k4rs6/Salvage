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
