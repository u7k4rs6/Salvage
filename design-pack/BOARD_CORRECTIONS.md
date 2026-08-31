# Board corrections

Written 2026-08-26, after the first board capture. This file overrides `04_FRONTEND_SPEC.md`
wherever the two disagree. The spec is a frozen M1 document and is kept in the pack for context;
it was written before the API existed and it describes two things the API does not do.

Everything below is checked against the shipped route source, not against the spec:

- `GET /api/overview` and `GET /api/incidents` are both in `salvage/api/routes_incidents.py`.
  There is no `routes_overview.py`.
- The 20 attempt floor is `salvage/detect/thresholds.py`, `min_attempts: int = 20`.
- The segment roster is `salvage/sim/params.yaml`, `traffic:`.

## 1. The three changes

### 1.1 The merchant success rate and attempts-last-hour tiles stay

**Corrected 2026-08-26. This section previously said the two tiles had been dropped and that the
stats row went from four to two. That was wrong, and a reader acting on it would remove two
working tiles.** No code change was ever made. All four tiles were present in
`web/src/pages/Overview.tsx` throughout and are present now, so the instruction to drop them was
a no-op rather than something later restored.

The premise behind the original instruction does not hold. Read 2.1: `/api/overview` returns both
`stats` and `series`, `series` matches the spec field for field, and the committed capture carries
`attempts_last_hour: 773` and `success_rate: 0.8835705045278137`. Those two tiles always have a
number.

The tile with the real defect is `recovered`, and 2.1 says what is wrong with it. It is relabelled
rather than dropped, because the number is real and only its label was ever wrong:

- **Recovered, all time**, with "link and steer routes only, excludes organic recovery" beneath.
- Never "today". The route applies no time filter at all.

`at_risk_amount` also stays. It reads 0 only when no incident is open, which is a true statement
about the merchant, not an empty tile.

### 1.2 An empty node is muted and labelled, never hidden

The board cannot do this from the payload alone. `_persist_stats` in `salvage/detect/run.py`
writes a `segments_stats` row **only for windows where the key was live**, meaning at least 20
attempts, and `overview()` returns early on `row is None`. So a key below the floor is not a row
with `attempts: 0`. It is absent from `segments` entirely, indistinguishable from a key that does
not exist.

To render the node at all the board needs the expected key list held client-side and diffed
against the response. `segment_roster.json` in this pack is that list, generated from
`salvage/sim/params.yaml` rather than transcribed. 33 nodes.

Three states per node, not two:

| state | condition | treatment |
|---|---|---|
| measured | key present in `segments` | normal tile, success rate and baseline |
| below detection floor | key in the roster, absent from `segments` | muted, label "below detection floor", no rate, no colour |
| in an open incident | `incident_id` is not null | red outline, links to the incident |

The muted tile carries no number. Do not substitute a stale rate from an earlier window: the
route reads one window, see 2.3.

### 1.3 Collapse a group that is empty in every capture

Two groups qualify, and only one of them for the reason given:

- **Wallet instruments.** `wallet` is not one of `INSTRUMENT_DIMENSIONS` in
  `salvage/detect/segments.py`. The dimensions are `card_bin6`, `upi_handle`, `nb_bank`,
  `card_issuer`, `card_network`. A wallet attempt therefore produces the `all` key and the
  `wallet` method key and nothing else. There are no wallet instrument tiles to render at any
  volume, in any capture. Collapse to one row and label it "no instrument dimension", which is a
  different statement from "below detection floor".
- **Netbanking banks.** All five exist as keys but none of them can reach 20 attempts in a
  15 minute window at this traffic level. Netbanking is 10 percent of the mix and the largest
  bank is 30 percent of that, so the busiest netbanking bank sees about 9 attempts in a peak
  window against a floor of 20, and the smallest sees 3. Collapse to one row labelled "below
  detection floor at all hours".

**`card_network` does not qualify and should stay expanded.** It is the densest card dimension,
not the sparsest: three values rather than five, and Visa carries two of the five BINs, so Visa
is about 12.5 percent of all attempts. It is the one card tile that survives a mid-range window,
and it is the only card instrument in the committed capture. `card_bin6` and `card_issuer` are
the sparse card groups: two of five reach the floor at peak, none off peak.

## 2. API gaps

Recorded, not fixed. The backend is frozen.

### 2.1 The stats tiles: which are backed

The route does return `stats` and `series`, and `series` matches the spec field for field. The
committed capture in `salvage_api_samples.json` carries `attempts_last_hour: 773` and
`success_rate: 0.8835705045278137`. Per tile:

| spec tile | field | backed |
|---|---|---|
| attempts in the last hour | `stats.attempts_last_hour` | yes, count over the last 3600 sim seconds |
| merchant-wide success rate | `stats.success_rate` | yes, but `null` when the last hour had no attempts, which is the first hour of a run |
| at-risk revenue (open incidents) | `stats.at_risk_amount` | yes, but sums **open** incidents only, so it is 0 whenever nothing is open, which is most of a run and is the case in the committed capture |
| recovered today | `stats.recovered_amount` | **mislabelled.** No time filter at all, so it is all-time, not today. It also reads `recovery_routes WHERE route IN ('link','steer')`, which excludes organic recovery |

So the two tiles the original instruction wanted dropped are the two that always have a number,
and the two it wanted kept are the two with the real problems. All four stay, see 1.1. The at-risk
tile will populate on a mid-run capture with the incident open, which is what a recapture fixes.
The recovered tile will not become "today" by recapturing, so it is relabelled instead.

### 2.2 Two different definitions of "recovered" in one payload

`stats.recovered_amount` sums `recovery_routes` where the route was `link` or `steer`.
`incidents[].recovered_amount` sums `recovery_cases` where `outcome = 'RECOVERED'`, which
includes cases that recovered organically. Different tables, different filters, different
populations. The merchant-wide tile and the incident cards can never be added up or reconciled
against each other, and the board should not place them where a reader will try.

### 2.3 The heatmap reads one window, not the most recent window per key

`_latest_window()` takes `MAX(window_start)` across the whole `segments_stats` table and then
selects `WHERE window_start = ?` for that single value. Any key that was live 15 minutes ago and
is not live in that one window disappears from the board.

`docs/BUILD_LOG.md` states "The dashboard's heatmap reads the most recent tested window per key",
and the docstring on `_persist_stats` repeats it. Neither is true of the shipped route. This is
the mechanism behind the empty board: it is not just that keys are sparse, it is that they must
all be sparse *in the same 15 minutes* to appear together.

It is also why a peak capture helps so much. See 2.4.

### 2.4 The operating envelope, in numbers

Traffic is 12,000 attempts per day and the diurnal curve peaks at 21:00 IST with a weight of
2.60 against a mean weight of 1.029, so a 15 minute window holds about 125 attempts on average
and about 316 at the peak. Against a floor of 20:

**Corrected 2026-08-26: the peak row said 375 attempts and about 21 nodes.** That came from
reading the params comment's "about 1,500 per hour at the evening peak" as three times the mean.
The curve says 2.53 times, so the peak window is 316 attempts and 15 nodes, not 21.
`segment_roster.json` now computes the peak from the weights instead of guessing a multiplier,
and carries the per-hour counts under `_nodes_clearing_floor_by_hour_ist`.

**Treat every number in this table as a centre, not a promise.** Eleven of the 33 sit within a
quarter of the floor either side at peak, so they flip in and out of the response on ordinary
Poisson noise: `card_bin6:555555`, `card_issuer:ICIC`, both of `card_network:MasterCard` and
`RuPay` at 19.7 expected, `upi_handle:paytm` and `nb_bank:PYTM` at 18.9, and the `wallet` method
row itself at 15.8. A peak capture will land somewhere around 13 to 19, not on 15. The roster
flags these with `marginal_at_peak` and the board says so in the tile's tooltip.

| window | attempts | nodes with a rate, out of 33 |
|---|---|---|
| 03:00 IST, the trough | 10 | 0 |
| 15:00 IST | 121 | 5 |
| the committed capture | 193 | 10 |
| 19:00 IST | 255 | 13 |
| 21:00 IST, the peak | 316 | 15 |
| 23:00 IST | 158 | 7 |

18 of the 33 do not reach the floor even at the peak: all 5 netbanking banks, 4 of the 5 card
BINs, the 4 card issuers behind them, 2 of the 3 card networks, `upi_handle:paytm` with its
`nb_bank:PYTM` twin, and the `wallet` method row. Nine of those 18 are the marginal ones above
and will appear in some captures. `segment_roster.json` carries the per-node arithmetic.

**Corrected 2026-08-26: the capture row said 6, and 6 was an artifact of the truncation in
section 3, not a measurement.** The response carried 10 segments. `salvage_api_samples.json` holds
the first 6 and then the sentinel `"...4 more items of the same shape"`, and the route's ordering
is what makes the cut so misleading: `overview()` emits the pinned `all` row, then the four method
rows, then everything else in `sorted(by_key)` order. Sorted, `card:card_network:Visa` and the
`upi:nb_bank:*` keys come before the `upi:upi_handle:*` keys, so the cap at five landed exactly
where the handle keys begin and removed the entire `upi_handle` dimension from the sample.

The tell was an impossible pair sitting in the fixture: `upi:nb_bank:HDFC` present with 25
attempts while `upi:upi_handle:okhdfcbank` was absent. Those two keys are built from the same
attempts by `keys_for_attempt` in `salvage/detect/segments.py`, so they carry identical attempt
counts and one cannot clear the floor without the other. A key that must be there and is not is a
missing-data bug, not a sparse window, and the only thing that could remove it was the cap.

The 10 are also exactly what the roster predicts. At 193 attempts the floor of 20 needs a share of
at least 0.104, which admits `all`, `upi`, `card`, both `ybl` keys, both `okhdfcbank` keys, both
`oksbi` keys and `card:card_network:Visa`. Ten. The uncapped peak capture should land near 21 of
33, not "21 instead of 6".

This is worth stating on the board rather than hiding. A detector with a 20 attempt floor and a
15 minute window can only see segments above a volume line, and that line is high relative to a
real merchant's long tail. It is the honest limitation and it is already the top item in
`docs/RESULTS.md` limitations.

### 2.5 A UPI segment can be labelled with a bank name

`salvage/sim/traffic.py:178` puts the UPI handle's bank into the payment entity's `bank` field,
and the normalizer writes `bank` to the `nb_bank` column for every method. So UPI produces both
`upi:upi_handle:okhdfcbank` and `upi:nb_bank:HDFC`, and the committed capture contains
`upi:nb_bank:HDFC` and `upi:nb_bank:SBIN` but no `upi_handle` key at all.

On the board that renders as method UPI, instrument "HDFC", which reads as a netbanking bank
sitting in the UPI row. Label the dimension, not just the value: "HDFC (handle bank)" under UPI
against "HDFC (bank)" under Netbanking. Ten of the 33 nodes are UPI, five on each dimension, and
they describe the same traffic twice.

### 2.6 `segments` has a field the spec omits

The route returns `failure_rate` alongside `rate`. The spec contract in section 4.1 lists
`{key, method, instrument, attempts, failures, rate, baseline, incident_id}`. `types.ts` in this
pack is correct, the spec is not.

## 3. The committed fixture is truncated in a way that will break a board

Not an API gap, my error when I built this pack. Every array in `salvage_api_samples.json` was
capped at 5 entries and a **bare string** was appended in place of the remainder:

```
"...4 more items of the same shape"
```

23 arrays carry one, including `overview.segments`, `overview.series`, `incidents/{id}.cases`,
`incidents/{id}.timeline`, `plan.actions` and every `gate` array. A board that maps over
`segments` will hit a string where it expects an object, which is exactly the shape of the
`TypeError: string indices must be integers` this pack produces when read naively.

The real capture had 10 segments and 124 series points, not 6 and 6.

When recapturing: keep the arrays whole, or slice them, but do not append a sentinel into a typed
array. The whole file is 27 KB with the caps in place; uncapped it is still small enough to paste.

## 4. Flagged, not fixed: the numbers that do not reconcile

> this fixture reports recovered 20,059 against at risk 21,048 on one incident, and 206 actions
> on 194 cases. Neither reconciles with the S1 figures in RESULTS.md.

**Endpoint:** `_incident_summary()` at `salvage/api/routes_incidents.py:135`. It is the shared
builder for three responses, so the payload could have come from `GET /api/incidents` (list row),
`GET /api/incidents/{id}` (the `incident` object), or `GET /api/overview` (inside `incidents[]`).
The pack captured the first two and they are byte-identical for this incident.

**Arm:** the agent arm, scenario S1, seed 1, from a live demo database with
`llm_provider: "fixture"`. That is the header note on `salvage_api_samples.json` and it is a
single seed, not the sweep.

**Why it does not reconcile: the two amounts are not a ratio.** They are paise, so 21,04,883 and
20,05,941 are 21,048.83 and 20,059.41 rupees, and the 95.3 percent that falls out of dividing
them is an artifact of dividing two unrelated sums.

- `at_risk_amount` is written once, at incident open, by `at_risk_amount()` in
  `salvage/detect/incidents.py:262`. It sums order amounts for failed attempts **inside the
  detection window only**, `window_start` to `evaluated_at`, which for this incident is the 15
  minutes from 1786199280 to 1786200180, and only for orders **still unpaid at that instant**.
  The evidence packet for the same incident reports 51 attempts and 22 failures in that window.
- `recovered_amount` is computed fresh on every request and sums every `recovery_cases` row for
  the incident with `outcome = 'RECOVERED'`, over the incident's **whole life**, which here is
  1786200180 to 1786206420, 104 minutes. It is not restricted to the at-risk set and not
  restricted to the detection window.

So the numerator covers about seven times the time span of the denominator and a different
population. Do not render these two as a rate, a percentage, or a progress bar. Show them as two
separate figures with their scopes named, or drop the at-risk figure from the incident card.

**RESULTS.md measures something else again.** Its at-risk set is every order whose *first*
attempt failed inside a *fault* window on the *fault's* instrument, taken from the world's fault
schedule, over the whole evaluation day, and averaged over ten seeds. That definition never looks
at the detector; the API's never looks at the fault schedule. They are different code paths,
`salvage/eval/metrics.py` against `salvage/detect/incidents.py`. For S1 the agent arm reports 262
at-risk orders and 2,21,154.50 rupees recovered from them, at a rate of 0.477. Nothing in the API
payload is comparable to any of those three numbers.

**206 actions on 194 cases is not 1.06 actions per case.** `cases` counts rows in
`recovery_cases` for the incident including ones that ended `CLOSED_NO_ACTION`, which the sample
case in this very fixture is. `actions` counts rows in the `actions` table for the incident,
which includes incident-scoped actions carrying `case_id: null`, and the `STEER_METHOD` in the
same payload is exactly that. A case can also carry several actions, a link and then nudges.
Different units on both sides. Neither is the message count: RESULTS.md has the S1 agent arm at
90 messages.

None of this is a bug in the numbers. It is three measurement definitions that share four field
names. The board should never place two of them where a reader will divide one by the other.
