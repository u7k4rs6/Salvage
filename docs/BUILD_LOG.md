# Salvage build log

Dated entries from day one of coding. Each entry records a decision on an open item, a frozen
threshold, or something that broke with what fixed it and what test now guards it. No em dashes or
en dashes anywhere in this repository, by instruction.

---

## 2026-08-24, M1 step 1: repository skeleton

### Decisions on open items

- **Docs location.** The four specs arrived in `files/`. Architecture section 13 puts them in
  `docs/`, so they were moved there unchanged. Reason: the layout in the spec is the spec.
- **CLI framework.** Architecture section 14 lists no CLI library. The minimal CLI uses stdlib
  `argparse` rather than adding typer or click. Reason: no dependency beyond the fixed list, and
  seven subcommands do not need more.
- **Secret scanner.** Section 3 of the security doc allows "gitleaks or the `detect-secrets`
  baseline". Neither is used. `scripts/scan_secrets.py` is a self-contained regex scanner run by
  `.githooks/pre-commit` and by CI. Reason: it needs no network, no extra dependency and no
  baseline file that drifts out of date. It also refuses any commit that includes `.env`.
  Install the hook with `git config core.hooksPath .githooks`.
- **`apscheduler`.** Architecture section 14 says "apscheduler or a hand-rolled asyncio loop
  (decide in M2)". Not added in M1. Reason: nothing in M1 schedules anything; the simulator drives
  its own clock.
- **Empty Razorpay key id is allowed.** The security doc says startup refuses a key id that is not
  a test key. It is refused when present. An absent key id is allowed so the simulator, detector
  and ledger run with no credentials at all, which is what CI does. Any code path that actually
  calls Razorpay goes through `Settings.require_razorpay_credentials()`, which refuses both an
  empty and a non-test key id.
- **Python version pin.** `requires-python = ">=3.12,<3.13"`. Reason: system Python 3.14 is
  externally managed and the project pins a uv-managed 3.12 per Architecture section 14. The upper
  bound stops a stray 3.13 or 3.14 interpreter from resolving.

### What broke

- `uv sync` failed with `OSError: Readme file does not exist: README.md` because `pyproject.toml`
  declared a readme before the file existed. Fixed by writing `README.md` before syncing. No test
  guards this; CI would catch it on the first `uv sync`.

---

## 2026-08-24, M1 step 2: migrations and repository layer

### Decisions on open items

- **Razorpay error taxonomy, Architecture section 17 open item.** Pulled from the official docs
  and transcribed into `salvage/taxonomy.py` with the source URLs in the module docstring. What
  was found:
  - `error_source` is published per payment method on
    `razorpay.com/docs/errors/payment-error-parameters`. Cards, UPI, netbanking, wallet, cardless
    EMI and emandate each have their own list; the union is ten values.
  - `error_step` is published on the same page but only inside the flow diagrams, which the
    rendered page draws as images. The values were recovered from the page's own MDX payload and
    cross-checked against the `payment_authentication` example on `razorpay.com/docs/errors/`.
    Cards get four steps, netbanking and emandate three, wallet and cardless EMI four, UPI eleven
    (Intent and Collect publish the same eleven in a different order).
  - `error_reason` has 110 published values in the downloadable sheet linked from the errors
    pages, `payments_error_reasons.xlsx`. All 110 are transcribed.
  - `error_code` is not published as an exhaustive enum. `BAD_REQUEST_ERROR` and `SERVER_ERROR`
    appear on the common errors page; `/docs/errors/payments/list/` groups reasons under two
    headings, "Bad Request Errors" and "Gateway Errors", which is where `GATEWAY_ERROR` comes
    from. Those three are the enum.
- **Enums are open, with passthrough.** Required by Architecture section 17 and confirmed as
  necessary by Razorpay's own data: the `payment.failed` webhook sample on
  `razorpay.com/docs/webhooks/payloads/payments/` carries `"error_source": "bank"`, and "bank"
  appears in the published per-method source lists only for Emandate, not for cards. So the
  published lists are not exhaustive, and `coerce_source`, `coerce_step` and `coerce_reason` pass
  unknown values through unchanged. `is_known_*` reports whether a value was published.
  Guarded by `tests/unit/test_taxonomy.py::test_unknown_values_pass_through_rather_than_raise`.
- **Reason to error_code mapping overlap.** Fourteen reasons appear under both headings on
  `/docs/errors/payments/list/`, for example `authentication_failed` and `payment_timed_out`.
  `error_code_for_reason` resolves the overlap to `GATEWAY_ERROR`. Reason: a payment that reached
  the gateway is the case the detector cares about, and a single deterministic mapping is needed
  so the simulator emits one code per reason.
- **Typo in Razorpay's own sheet.** Row `psp_app_ not_available` in the xlsx has a stray space.
  `/docs/errors/payments/list/` spells it `psp_app_not_available`. The list-page spelling is used.
- **UPI flow modelled.** UPI Intent, not Collect. Reason: the error parameters page states UPI
  Collect is deprecated from 28 February 2026 under NPCI guidelines.
- **`salvage/taxonomy.py` and `salvage/repo.py` are new modules.** Architecture section 13 lists
  neither. Reason: section 14 says "plain `sqlite3` with a thin repository layer" without naming
  the file, and the taxonomy is imported by sim, ingest, detect and diagnose, so it belongs in one
  module rather than duplicated. No dependency was added for either.
- **Ground truth isolation.** `payment_attempts.truth_cause` plus `sim_runs`,
  `sim_truth_attempts` and `sim_truth_incidents` hold ground truth. Agent code paths read
  `v_payment_attempts`, `v_orders` and `v_customers`. The views are asserted to differ from the
  base table by exactly the `truth_cause` column, so adding a truth column to
  `payment_attempts` later and forgetting the view will fail the test.
  Guarded by `tests/unit/test_db_schema.py::test_agent_view_excludes_truth_cause`.
- **Out-of-order safety lives in the upserts.** Security doc section 4 says out-of-order delivery
  is safe because normalisation is upsert-by-entity-id and transitions are guarded. That guard is
  implemented in `repo.upsert_order` and `repo.upsert_attempt`: a paid order never reverts, a
  captured attempt never reverts to failed, an authorized attempt never reverts to failed.
  Guarded by `test_order_paid_state_is_sticky_for_out_of_order_events` and
  `test_attempt_captured_state_is_sticky`.
- **Columns added beyond the section 3 list.** `customers.alt_*` (the secondary instrument the
  merchant fixture in Architecture section 9 gives roughly 60 percent of customers, needed by the
  policy engine's alternate-method check), `customers.created_at`,
  `incidents.affected_scope_json` (section 5 requires child keys recorded as affected scope),
  `webhook_events.event_type`, `webhook_events.stale` and `webhook_events.acted` (section 4 of the
  security doc requires stale events to be stored, flagged and not acted on),
  `escalations.note` and `escalations.created_at`, `checkout_hints.incident_id`. Each is additive
  and named after the requirement that asked for it.

---

## 2026-08-24, M1 step 3: ledger

### Decisions on open items

- **Genesis constant.** `GENESIS_HASH = sha256(b"salvage.ledger.genesis.v1").hexdigest()` =
  `e033221f96520f784ef136e1ba52ae6b04cba31331157e223f1c97e64ae59524`. The security doc says "a
  fixed genesis constant" without fixing the value. A hash of a version-tagged string rather than
  64 zeroes, so a future chain format can pick a different one and old exports cannot be replayed
  as new ones.
- **Pre-image encoding.** The doc writes the rule as
  `sha256(seq || ts || kind || ref_type || ref_id || canonical_json(payload) || prev_hash)` and
  does not say what `||` is. It is implemented as each field's UTF-8 bytes followed by a newline.
  Reason: `canonical_json` uses `json.dumps(..., ensure_ascii=True)`, which escapes every control
  character, so no field can contain a raw newline and no attacker can shift bytes between fields
  to forge a matching pre-image. A bare concatenation would have been ambiguous.
- **`payload_json` is stored, not re-serialised.** The exact canonical string that was hashed is
  what goes in the column and the export, so a verifier never has to agree with us about float
  formatting or key order.
- **Overlap resolution for an empty ledger's head hash.** `verify` on an empty chain reports the
  genesis constant as the head, matching what `scripts/verify_ledger.py` prints, so both tools
  produce the same shape of output.
- **`scripts/verify_ledger.py` imports nothing from the package.** Standard library only, its own
  copy of the constant and the hash rule, about fifty lines with the docstring. Reason: the point
  of an offline verifier is that a reviewer does not have to trust the code being audited. It also
  refuses an export whose declared genesis hash differs from its own constant, so the header is
  informational and not authoritative.

### What broke

- `test_export_contains_no_phone_or_email` failed against a clean export. The Indian mobile
  pattern `(?<!\d)[6-9]\d{9}(?!\d)` matched a ten-digit run inside a 64-character sha256
  `ref_hash`. Fixed by anchoring the pattern on alphanumeric boundaries rather than digit
  boundaries, which is what a real phone number in text looks like. The test now guards the export
  and would still catch a genuine leak.
- The Hypothesis mutation test failed twice, both times in the test's own mutation helper, not in
  the ledger. First, flipping a byte inside a multi-byte UTF-8 character and decoding with
  `surrogateescape` produced a lone surrogate that could not be re-encoded when the hash was
  recomputed; fixed by decoding with `errors="replace"`. Second, mutating the `seq` field makes
  `verify` report the sequence number it found rather than the one it expected, so asserting
  `broken_seq in (target + 1, target + 2)` was wrong; the assertion is now that a break is
  reported at all. Guarded by
  `tests/property/test_ledger_mutation.py::test_any_single_byte_mutation_fails_verification`
  at 300 examples, plus a reordering property.
- `test_shipped_source_has_no_ledger_mutation` failed on `salvage/ledger.py` itself: the module
  docstring quoted the two forbidden SQL phrases while explaining the rule. Fixed by rewording the
  docstring so the patterns live only in the test. The grep test also carries two self-checks, one
  asserting the patterns match real mutating SQL and one asserting they do not fire on
  `INSERT INTO ledger` or on `UPDATE incidents`, so a grep that silently stopped matching would
  itself fail.

---

## 2026-08-24, M1 step 4: simulator

### Decisions on open items

- **Traffic volume, and why it moved.** Architecture section 9 says "about 1,500 attempts per
  day". `sim/params.yaml` uses 12,000, and the customer base moves from 2,000 to 8,000 with it.
  The arithmetic: the detector in Architecture section 5 will not evaluate a key with fewer than
  20 attempts in a 15-minute window, and PRD goal G1 requires detection within 15 simulated
  minutes. At 1,500 attempts a day, UPI is 900 of them, one of five handles carries roughly 230,
  and a 15-minute window on that handle holds about 2.4 attempts. The n >= 20 rule can never fire
  on the segment S1 breaks, so the 15-minute target is unreachable by construction. The two
  figures in the documents are mutually inconsistent and one had to move. Volume moved, because
  the detection target is a product requirement (G1, a row in the metrics table) and the traffic
  figure is an illustration in an architecture note. At 12,000 a day the S1 segment sees about 40
  attempts per 15-minute window at the evening peak, which clears the rule in about eight
  minutes. Customers moved with it because 2,000 customers making 12,000 attempts a day is six
  orders per customer per day, which no D2C store sees; 8,000 gives about 12 orders per customer
  across the eight simulated days. Both numbers and this reasoning are in `params.yaml` beside the
  values. Guarded by `tests/unit/test_sim.py::test_s1_run_writes_events_and_ground_truth` and by
  the calibration table in step 6.
- **Faults are scheduled in the evening peak.** Every fault in `params.yaml` starts between 19:00
  and 20:00 IST, with a seed-dependent jitter of up to 90 minutes. This is load bearing and is
  written beside the values: time to detect is a function of volume, so scheduling a fault at
  03:00 would measure the trough rather than the detector. It is also the realistic case, since
  rail degradation is most likely and most expensive when volume is highest. The jitter is
  derived from the seed arithmetically rather than drawn from a random stream, so it cannot shift
  the customers or arrivals that stream would otherwise have produced.
- **S1 uses `error_source: bank`.** Architecture section 9 says S1 sets the UPI handle to fail
  with "bank source". `bank` is not in Razorpay's published source list for UPI, which has
  `issuer_bank`. It is kept because it is what the document asks for, because it is what
  Razorpay's own `payment.failed` webhook sample emits, and because the rules classifier in
  Architecture section 6 already expects either ("dominant source is `bank` or `issuer_bank`"). It
  also exercises the taxonomy passthrough on real data rather than only in a test.
- **Ledger granularity for simulated traffic.** The architecture diagram has ingest feeding the
  ledger. The simulator appends two entries per run, `sim.run.started` and `sim.run.finished`, not
  one per attempt. Reason: the ledger is an audit trail of what Salvage did, and Salvage did not
  act on a simulated attempt; generating the batch is one act. One entry per attempt would also be
  96,000 separate write transactions per run and would make `ledger verify` and the ledger page
  useless. Real webhook events are ledgered one entry per verified event in step 5, which is where
  per-event auditability actually matters. Guarded by
  `tests/unit/test_sim.py::test_run_appends_exactly_two_ledger_entries_and_the_chain_verifies`.
- **`truth_cause` values.** `none` for a successful attempt, `organic` for a failure that would
  have happened anyway, and one of the six root-cause classes for a fault-caused failure. The
  migration comment said "one of the six causes, or 'none' for a success"; `organic` was added,
  because PRD section 10 requires ground truth to say "whether it was fault-caused or organic" and
  a two-value column cannot. The counterfactual (`p_organic`, `organic_retry_at`) lives in
  `sim_truth_attempts` and exists for failed attempts only, since a successful payment has no
  retry to counterfactualise.
- **Every attempt uses the customer's preferred instrument.** The alternate instrument exists so
  the M2 policy engine can ask whether a customer has another rail. It is not used for traffic, so
  the observed method mix equals the configured mix exactly rather than approximately.
- **Fixed draw count in the response model.** `ResponseModel.draw` consumes exactly three values
  from the response substream on every call, whatever the branch taken. Without that, adding an
  intervention branch in M2 would shift every later order's draws and the "shared random stream
  per seed" guarantee would silently break between M1 and M2.
- **Two new modules in `salvage/sim/`.** `clock.py` (the sim clock and IST arithmetic, needed by
  traffic, faults and the detector) and `params.py` (the YAML loader and its validation).
  Architecture section 13 lists neither. No dependency was added.
- **The parameter file validates itself.** `params.load()` refuses a file whose shares do not sum
  to one, whose diurnal curve is not 24 positive hours, or whose error profiles name a reason,
  step or source Razorpay does not publish. A typo in a reason name would otherwise reach
  `docs/RESULTS.md` unchallenged. Guarded by
  `tests/unit/test_sim.py::test_bad_reason_in_params_is_refused`.
- **S5 is refused, not silently skipped.** `params.yaml` carries S5's parameters with
  `implemented: false` so the file describes the whole instrument, and `run_scenario` raises if
  asked for it. PRD section 10 marks S5 stretch and the M1 brief says to skip it.

### What broke

- Nothing failed in a way that needed a fix in this step. The first S1 run was checked by hand
  against the fault window before any test was written: the affected UPI handle failed at 93.1
  percent against siblings at 5 to 12 percent, the method mix came out 59.4 / 24.9 / 10.3 / 5.4
  against a configured 60 / 25 / 10 / 5, and a full eight-day run took 3.2 seconds.
- One performance change was made before it became a problem: the fault error-profile sampler was
  being rebuilt for every attempt inside the fault window. It is now built once per fault.

---

## 2026-08-24, M1 step 5: ingest

### Decisions on open items

- **An unverified body is not stored.** The security doc says verification is the authentication
  and that verified events are normalised, but it does not say what happens to a body that fails
  verification. It is rejected with 400 and nothing is written. Reason: storing it would let
  anyone who finds the URL fill the database, and there is no audit value in a record of
  unauthenticated noise. Guarded by
  `tests/unit/test_webhooks.py::test_bad_signature_is_rejected_and_stores_nothing`.
- **Customer resolution for a real webhook.** Razorpay's payment entity has no Salvage customer
  id. If the order is already known, its customer is used. Otherwise a customer is created with
  `consent = 0` and a salted `ref_hash` derived from whatever identifier the payload carries
  (contact, then email, then the order id). Consent defaults to off, so the policy engine refuses
  to contact someone Salvage has never met. The raw contact stays only in
  `webhook_events.raw_json`, which is what security doc section 5 allows and what the ledger and
  exports exclude. Guarded by `test_a_customer_is_created_for_an_unknown_order` and
  `test_the_ledger_entry_carries_no_contact_or_email`.
- **The normaliser derives the UPI handle from the VPA.** Razorpay does not publish the handle as
  its own field, so it is the part after the `@`. That derivation is isolated in one function,
  `_upi_handle`, so if Razorpay adds a handle field only that function changes. This is the one
  place in the ingest path where Salvage infers rather than reads.
- **Wallet code shares a column with the bank code.** `payment_attempts.nb_bank` holds the
  4-character bank code for netbanking and UPI and the wallet code for wallets, so a single
  segment key means "which instrument inside this method" for every method. Recorded because the
  column name now says less than it holds.
- **A missing webhook secret returns 503, not 500.** The server cannot verify anything without
  it. 503 is the honest status and Razorpay retries on it.
- **A payload with no `created_at` counts as fresh.** Razorpay always sends one; refusing to act
  because a field outside Salvage's control is absent would be worse than acting.
- **Payment link handling exists but does nothing yet.** M1 creates no links, so there is never a
  matching recovery case. The lookup is written now so a replayed or out-of-order link event is a
  recorded no-op today and correct in M2 without a second code path.

### What broke

- Every webhook endpoint test failed with `sqlite3.ProgrammingError: SQLite objects created in a
  thread can only be used in that same thread`. This was not a test artefact: FastAPI runs a
  synchronous dependency generator in a worker thread while an `async def` endpoint body runs on
  the event loop thread, so a connection created by the dependency legitimately crosses threads on
  every real request too. Fixed by opening connections with `check_same_thread=False` in
  `salvage/db.py`, with a comment saying why that is safe here: Salvage is single-process, every
  write goes through `BEGIN IMMEDIATE`, and `busy_timeout` is set. The whole endpoint test file
  guards it.
- `test_replay_route_does_not_exist_in_demo` failed, and it was a real security defect rather
  than a test problem. The webhook router was a module-level singleton and
  `register_dev_replay_route()` mutated it in place, so once any dev-mode app had been created in
  a process, every later app in that process carried the unsigned replay route, including a
  demo-mode one. Fixed by replacing the singleton with `build_router(include_dev_replay=...)`,
  which builds a fresh router per application, so "compiled out of the router otherwise" is
  literally true. The endpoint itself also still refuses outside dev, as defence in depth.
  Guarded by `test_replay_route_exists_in_dev` and `test_replay_route_does_not_exist_in_demo`.
