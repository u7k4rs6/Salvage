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
