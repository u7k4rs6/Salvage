-- Salvage initial schema. Every table in docs/02_TECHNICAL_ARCHITECTURE.md section 3.
--
-- Conventions, fixed by that section:
--   Amounts are integers in paise. Never a float, never rupees.
--   Timestamps are integer Unix seconds. The sim clock supplies them in simulation, the wall
--   clock when ingesting real webhooks.
--   Booleans are integers 0 or 1.
--
-- Ground truth (payment_attempts.truth_cause and the sim_truth_* tables) is readable only by the
-- evaluation runner. Agent code paths read the v_* views defined at the bottom of this file, which
-- do not expose it.

CREATE TABLE customers (
    id              TEXT PRIMARY KEY,
    ref_hash        TEXT NOT NULL UNIQUE,   -- salted SHA-256, used for joins and display
    consent         INTEGER NOT NULL DEFAULT 0,
    locale          TEXT NOT NULL DEFAULT 'en',   -- en or hi_en
    preferred_method TEXT,
    upi_handle      TEXT,
    card_bin        TEXT,
    card_network    TEXT,
    card_issuer     TEXT,
    nb_bank         TEXT,
    typical_amount  INTEGER NOT NULL DEFAULT 0,   -- paise
    opted_out_at    INTEGER,
    -- Secondary instrument, so the policy engine can ask "does this customer have an alternate".
    alt_method      TEXT,
    alt_upi_handle  TEXT,
    alt_card_bin    TEXT,
    alt_nb_bank     TEXT,
    created_at      INTEGER NOT NULL
);

CREATE TABLE orders (
    id          TEXT PRIMARY KEY,           -- Razorpay order id or sim id
    customer_id TEXT NOT NULL REFERENCES customers(id),
    amount      INTEGER NOT NULL,           -- paise
    currency    TEXT NOT NULL DEFAULT 'INR',
    status      TEXT NOT NULL,              -- created, attempted, paid, abandoned
    source      TEXT NOT NULL,              -- sim or razorpay
    created_at  INTEGER NOT NULL,
    paid_at     INTEGER
);
CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_orders_status_created ON orders(status, created_at);

CREATE TABLE payment_attempts (
    id                TEXT PRIMARY KEY,     -- Razorpay payment id or sim id
    order_id          TEXT NOT NULL REFERENCES orders(id),
    customer_id       TEXT NOT NULL REFERENCES customers(id),
    method            TEXT NOT NULL,        -- upi, card, netbanking, wallet
    upi_handle        TEXT,
    card_bin          TEXT,
    card_network      TEXT,
    card_issuer       TEXT,
    nb_bank           TEXT,
    status            TEXT NOT NULL,        -- failed, authorized, captured
    error_code        TEXT,
    error_source      TEXT,
    error_step        TEXT,
    error_reason      TEXT,
    error_description TEXT,
    created_at        INTEGER NOT NULL,
    raw_json          TEXT NOT NULL,        -- the Razorpay-shaped payment entity as received
    -- Ground truth. Simulator only. Never selected by agent code paths; use v_payment_attempts.
    truth_cause       TEXT
);
CREATE INDEX idx_attempts_created ON payment_attempts(created_at);
CREATE INDEX idx_attempts_order ON payment_attempts(order_id);
CREATE INDEX idx_attempts_status_created ON payment_attempts(status, created_at);

CREATE TABLE segments_stats (
    segment_key   TEXT NOT NULL,
    window_start  INTEGER NOT NULL,
    attempts      INTEGER NOT NULL,
    failures      INTEGER NOT NULL,
    baseline_rate REAL NOT NULL,
    p_value       REAL NOT NULL,
    PRIMARY KEY (segment_key, window_start)
);
CREATE INDEX idx_segments_window ON segments_stats(window_start);

CREATE TABLE incidents (
    id                 TEXT PRIMARY KEY,
    segment_key        TEXT NOT NULL,
    opened_at          INTEGER NOT NULL,
    closed_at          INTEGER,
    at_risk_amount     INTEGER NOT NULL DEFAULT 0,   -- paise
    rules_cause        TEXT,
    llm_cause          TEXT,
    root_cause         TEXT,
    confidence         REAL,
    plan_json          TEXT,
    status             TEXT NOT NULL,     -- open, escalated, paused, recovering, closed
    -- Child segment keys folded into this incident by coarsest-key attribution, JSON array.
    affected_scope_json TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX idx_incidents_status ON incidents(status);
CREATE INDEX idx_incidents_opened ON incidents(opened_at);

CREATE TABLE recovery_cases (
    id             TEXT PRIMARY KEY,
    order_id       TEXT NOT NULL REFERENCES orders(id),
    customer_id    TEXT NOT NULL REFERENCES customers(id),
    incident_id    TEXT REFERENCES incidents(id),
    state          TEXT NOT NULL,
    attempts       INTEGER NOT NULL DEFAULT 0,
    link_id        TEXT,
    link_url       TEXT,
    next_action_at INTEGER,
    ttl_at         INTEGER NOT NULL,
    outcome        TEXT,
    updated_at     INTEGER NOT NULL
);
CREATE UNIQUE INDEX idx_cases_order ON recovery_cases(order_id);
CREATE INDEX idx_cases_incident ON recovery_cases(incident_id);
CREATE INDEX idx_cases_next_action ON recovery_cases(next_action_at);

CREATE TABLE actions (
    id                TEXT PRIMARY KEY,
    case_id           TEXT REFERENCES recovery_cases(id),
    incident_id       TEXT REFERENCES incidents(id),
    type              TEXT NOT NULL,
    params_json       TEXT NOT NULL,
    gate_json         TEXT NOT NULL,     -- list of {rule, passed, detail}
    status            TEXT NOT NULL,     -- proposed, refused, executed, failed, suppressed
    rzp_request_id    TEXT,
    rzp_response_json TEXT,
    executed_at       INTEGER
);
CREATE INDEX idx_actions_incident ON actions(incident_id);
CREATE INDEX idx_actions_case ON actions(case_id);

CREATE TABLE escalations (
    id                   TEXT PRIMARY KEY,
    incident_id          TEXT NOT NULL REFERENCES incidents(id),
    reason               TEXT NOT NULL,
    evidence_json        TEXT NOT NULL,
    proposed_action_json TEXT,
    decision             TEXT,          -- approve, reject, null while pending
    decided_at           INTEGER,
    note                 TEXT,
    created_at           INTEGER NOT NULL
);
CREATE INDEX idx_escalations_decision ON escalations(decision);

CREATE TABLE customer_comms (
    id          TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    case_id     TEXT REFERENCES recovery_cases(id),
    incident_id TEXT REFERENCES incidents(id),
    channel     TEXT NOT NULL,
    template_id TEXT NOT NULL,
    locale      TEXT NOT NULL,
    body_hash   TEXT NOT NULL,          -- hash only: the ledger and exports carry no message body
    sent_at     INTEGER NOT NULL
);
CREATE INDEX idx_comms_customer_sent ON customer_comms(customer_id, sent_at);
CREATE INDEX idx_comms_incident ON customer_comms(incident_id);

CREATE TABLE webhook_events (
    event_id    TEXT PRIMARY KEY,       -- X-Razorpay-Event-Id, unique index is the dedupe
    received_at INTEGER NOT NULL,
    verified    INTEGER NOT NULL,
    raw_json    TEXT NOT NULL,          -- may contain contact details; never logged, never exported
    event_type  TEXT,
    -- Freshness check, docs/03_SECURITY_AND_ACCESS.md section 4: demo mode flags events whose
    -- payload created_at is more than the freshness window old. Stale events are stored, flagged
    -- and not acted on.
    stale       INTEGER NOT NULL DEFAULT 0,
    acted       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_webhook_received ON webhook_events(received_at);

CREATE TABLE llm_cache (
    prompt_hash   TEXT PRIMARY KEY,
    provider      TEXT NOT NULL,
    model         TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at    INTEGER NOT NULL
);

-- Append only. There is no UPDATE or DELETE path against this table anywhere in the codebase and
-- tests/unit/test_ledger_append_only.py greps the source to keep it that way.
CREATE TABLE ledger (
    seq          INTEGER PRIMARY KEY,   -- 1-based, assigned by the writer, gapless
    ts           INTEGER NOT NULL,
    kind         TEXT NOT NULL,
    ref_type     TEXT NOT NULL,
    ref_id       TEXT NOT NULL,
    payload_json TEXT NOT NULL,         -- canonical JSON, exactly the bytes that were hashed
    prev_hash    TEXT NOT NULL,
    hash         TEXT NOT NULL
);
CREATE INDEX idx_ledger_kind ON ledger(kind);
CREATE INDEX idx_ledger_ref ON ledger(ref_type, ref_id);
CREATE INDEX idx_ledger_ts ON ledger(ts);

CREATE TABLE checkout_hints (
    segment_key   TEXT NOT NULL,
    hide_json     TEXT NOT NULL,
    sequence_json TEXT NOT NULL,
    active_from   INTEGER NOT NULL,
    active_to     INTEGER,
    incident_id   TEXT REFERENCES incidents(id),
    PRIMARY KEY (segment_key, active_from)
);

-- ---------------------------------------------------------------------------
-- Simulator ground truth. Evaluation runner only.
-- ---------------------------------------------------------------------------

CREATE TABLE sim_runs (
    run_id      TEXT PRIMARY KEY,
    scenario    TEXT NOT NULL,
    seed        INTEGER NOT NULL,
    params_hash TEXT NOT NULL,       -- hash of sim/params.yaml, so a result names its instrument
    started_at  INTEGER NOT NULL,
    finished_at INTEGER,
    sim_start   INTEGER NOT NULL,    -- sim clock at the first generated attempt
    sim_end     INTEGER
);

CREATE TABLE sim_truth_attempts (
    attempt_id   TEXT PRIMARY KEY REFERENCES payment_attempts(id),
    run_id       TEXT NOT NULL REFERENCES sim_runs(run_id),
    fault_caused INTEGER NOT NULL,   -- 1 if the fault made this attempt fail, 0 if organic
    truth_cause  TEXT NOT NULL,      -- one of the six causes, or 'none' for a success
    p_organic    REAL NOT NULL,      -- organic retry probability drawn for this order
    organic_retry_at INTEGER         -- sim second of the counterfactual organic retry, or null
);
CREATE INDEX idx_truth_attempts_run ON sim_truth_attempts(run_id);

CREATE TABLE sim_truth_incidents (
    id               TEXT PRIMARY KEY,
    run_id           TEXT NOT NULL REFERENCES sim_runs(run_id),
    scenario         TEXT NOT NULL,
    segment_selector TEXT NOT NULL,  -- JSON of the fault's selector
    true_cause       TEXT NOT NULL,
    start_ts         INTEGER NOT NULL,
    end_ts           INTEGER NOT NULL
);
CREATE INDEX idx_truth_incidents_run ON sim_truth_incidents(run_id);

-- ---------------------------------------------------------------------------
-- Views for agent code paths. These exclude truth_cause and every sim_truth_* table.
-- Anything the detector, diagnosis, decision or executor reads goes through these.
-- ---------------------------------------------------------------------------

CREATE VIEW v_payment_attempts AS
SELECT
    id, order_id, customer_id, method, upi_handle, card_bin, card_network, card_issuer, nb_bank,
    status, error_code, error_source, error_step, error_reason, error_description, created_at,
    raw_json
FROM payment_attempts;

CREATE VIEW v_orders AS
SELECT id, customer_id, amount, currency, status, source, created_at, paid_at FROM orders;

CREATE VIEW v_customers AS
SELECT
    id, ref_hash, consent, locale, preferred_method, upi_handle, card_bin, card_network,
    card_issuer, nb_bank, typical_amount, opted_out_at, alt_method, alt_upi_handle, alt_card_bin,
    alt_nb_bank, created_at
FROM customers;
