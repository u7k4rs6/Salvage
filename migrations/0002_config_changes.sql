-- Merchant configuration change log.
--
-- The evidence packet in docs/02_TECHNICAL_ARCHITECTURE.md section 6 carries
-- merchant_config_changed_recently, and the rules classifier in the same section reads it. In a
-- real deployment that signal comes from the merchant's own audit log of dashboard and API
-- settings changes.
--
-- It must not come from simulator ground truth. The agent may not read truth_cause or any
-- sim_truth_* table, and "did the merchant change a setting" is exactly the kind of fact that
-- would smuggle the answer into the question. So the simulator writes a row here when a scenario
-- includes a configuration-changing fault, timed slightly before the errors start, because that
-- is the causal order, and the agent reads this table like any other merchant-side fact.

CREATE TABLE config_changes (
    id         TEXT PRIMARY KEY,
    changed_at INTEGER NOT NULL,
    area       TEXT NOT NULL,     -- payment_methods, banks, keys, webhooks, checkout
    detail     TEXT NOT NULL,     -- one line, no PII, safe to show a model
    source     TEXT NOT NULL      -- sim or razorpay
);
CREATE INDEX idx_config_changes_at ON config_changes(changed_at);

CREATE VIEW v_config_changes AS
SELECT id, changed_at, area, detail, source FROM config_changes;
