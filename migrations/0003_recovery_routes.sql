-- How a paid order came to be paid.
--
-- The headline metric in docs/RESULTS.md is total recovered revenue over an order set that is
-- identical for every policy, counting every route to payment including customers who came back
-- on their own. That number is only comparable if every route is counted, and it is only useful
-- if it can be decomposed, which needs the route recorded at the moment the payment happens
-- rather than inferred afterwards from which tables happen to have rows in them.
--
-- Routes: link (paid on a recovery Payment Link), steer (paid in the same session on an alternate
-- method after a checkout display hint moved them off the failing one), organic (the customer
-- came back on their own with no intervention).
--
-- One row per order. Attribution is first past the post: an order is paid once, and whichever
-- route got there first gets the credit. An order with no row here was paid organically or is
-- unpaid, which is why the metrics default to organic rather than to unknown.

CREATE TABLE recovery_routes (
    order_id  TEXT PRIMARY KEY REFERENCES orders(id),
    route     TEXT NOT NULL,     -- link, steer, organic
    paid_at   INTEGER NOT NULL,
    case_id   TEXT,              -- null for steer and organic
    policy    TEXT NOT NULL      -- which policy arm produced it, for the decomposition table
);
CREATE INDEX idx_recovery_routes_route ON recovery_routes(route);
