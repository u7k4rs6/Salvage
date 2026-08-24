"""Thin repository layer over sqlite3.

No ORM (docs/02_TECHNICAL_ARCHITECTURE.md section 14). Every function takes an open connection.
Two rules hold everywhere in this file:

  Agent-facing reads go through the v_* views, so truth_cause and the sim_truth_* tables cannot
  leak into a code path the agent uses. Functions that read ground truth are grouped at the bottom
  under a heading that names the evaluation runner as their only caller.

  There is no UPDATE or DELETE against the ledger table anywhere. The ledger writer lives in
  salvage/ledger.py and only appends.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Sequence
from typing import Any

from salvage.config import get_settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def ref_hash(raw_identifier: str, salt: str | None = None) -> str:
    """Salted SHA-256 used for joins and display, per security doc section 5.

    The salt comes from SALVAGE_REF_HASH_SALT. Rotating it invalidates existing hashes, which is
    stated in .env.example.
    """
    if salt is None:
        salt = get_settings().salvage_ref_hash_salt
    return hashlib.sha256(f"{salt}:{raw_identifier}".encode()).hexdigest()


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _insert(conn: sqlite3.Connection, table: str, values: dict[str, Any], *, or_: str = "") -> None:
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    verb = f"INSERT {or_} INTO" if or_ else "INSERT INTO"
    conn.execute(
        f"{verb} {table} ({columns}) VALUES ({placeholders})",
        tuple(values.values()),
    )


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------


def insert_customer(conn: sqlite3.Connection, customer: dict[str, Any]) -> None:
    _insert(conn, "customers", customer)


def insert_customers(conn: sqlite3.Connection, customers: Sequence[dict[str, Any]]) -> None:
    for customer in customers:
        insert_customer(conn, customer)


def get_customer(conn: sqlite3.Connection, customer_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM v_customers WHERE id = ?", (customer_id,)).fetchone()
    return dict(row) if row else None


def count_customers(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) AS n FROM customers").fetchone()["n"])


def set_opted_out(conn: sqlite3.Connection, customer_id: str, ts: int) -> None:
    conn.execute("UPDATE customers SET opted_out_at = ? WHERE id = ?", (ts, customer_id))


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


def upsert_order(conn: sqlite3.Connection, order: dict[str, Any]) -> None:
    """Upsert by id. Webhooks can arrive out of order, so a later event must not overwrite a
    terminal state with an earlier one: paid_at and a paid status are sticky.
    """
    conn.execute(
        """
        INSERT INTO orders (id, customer_id, amount, currency, status, source, created_at, paid_at)
        VALUES (:id, :customer_id, :amount, :currency, :status, :source, :created_at, :paid_at)
        ON CONFLICT(id) DO UPDATE SET
            status  = CASE WHEN orders.status = 'paid' THEN 'paid' ELSE excluded.status END,
            paid_at = COALESCE(orders.paid_at, excluded.paid_at),
            amount  = excluded.amount
        """,
        {
            "id": order["id"],
            "customer_id": order["customer_id"],
            "amount": order["amount"],
            "currency": order.get("currency", "INR"),
            "status": order["status"],
            "source": order["source"],
            "created_at": order["created_at"],
            "paid_at": order.get("paid_at"),
        },
    )


def get_order(conn: sqlite3.Connection, order_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM v_orders WHERE id = ?", (order_id,)).fetchone()
    return dict(row) if row else None


def mark_order_paid(conn: sqlite3.Connection, order_id: str, paid_at: int) -> None:
    conn.execute(
        "UPDATE orders SET status = 'paid', paid_at = COALESCE(paid_at, ?) WHERE id = ?",
        (paid_at, order_id),
    )


def count_orders(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"])


# ---------------------------------------------------------------------------
# Payment attempts
# ---------------------------------------------------------------------------

ATTEMPT_COLUMNS = (
    "id",
    "order_id",
    "customer_id",
    "method",
    "upi_handle",
    "card_bin",
    "card_network",
    "card_issuer",
    "nb_bank",
    "status",
    "error_code",
    "error_source",
    "error_step",
    "error_reason",
    "error_description",
    "created_at",
    "raw_json",
    "truth_cause",
)


def upsert_attempt(conn: sqlite3.Connection, attempt: dict[str, Any]) -> None:
    """Upsert by payment id. Out-of-order delivery is safe: a captured attempt never reverts to
    failed, which is the state-transition guard the security doc section 4 relies on.
    """
    values = {column: attempt.get(column) for column in ATTEMPT_COLUMNS}
    conn.execute(
        """
        INSERT INTO payment_attempts (
            id, order_id, customer_id, method, upi_handle, card_bin, card_network, card_issuer,
            nb_bank, status, error_code, error_source, error_step, error_reason, error_description,
            created_at, raw_json, truth_cause
        ) VALUES (
            :id, :order_id, :customer_id, :method, :upi_handle, :card_bin, :card_network,
            :card_issuer, :nb_bank, :status, :error_code, :error_source, :error_step,
            :error_reason, :error_description, :created_at, :raw_json, :truth_cause
        )
        ON CONFLICT(id) DO UPDATE SET
            status = CASE
                WHEN payment_attempts.status = 'captured' THEN 'captured'
                WHEN payment_attempts.status = 'authorized' AND excluded.status = 'failed'
                    THEN 'authorized'
                ELSE excluded.status
            END,
            error_code        = COALESCE(excluded.error_code, payment_attempts.error_code),
            error_source      = COALESCE(excluded.error_source, payment_attempts.error_source),
            error_step        = COALESCE(excluded.error_step, payment_attempts.error_step),
            error_reason      = COALESCE(excluded.error_reason, payment_attempts.error_reason),
            error_description = COALESCE(
                excluded.error_description, payment_attempts.error_description),
            raw_json          = excluded.raw_json
        """,
        values,
    )


def insert_attempts(conn: sqlite3.Connection, attempts: Sequence[dict[str, Any]]) -> None:
    for attempt in attempts:
        upsert_attempt(conn, attempt)


def get_attempt(conn: sqlite3.Connection, attempt_id: str) -> dict[str, Any] | None:
    """Agent-facing read. Goes through the view, so no truth_cause."""
    row = conn.execute("SELECT * FROM v_payment_attempts WHERE id = ?", (attempt_id,)).fetchone()
    return dict(row) if row else None


def attempts_between(
    conn: sqlite3.Connection, start: int, end: int
) -> list[dict[str, Any]]:
    """Attempts with created_at in [start, end). Agent-facing, view only."""
    rows = conn.execute(
        "SELECT * FROM v_payment_attempts WHERE created_at >= ? AND created_at < ? "
        "ORDER BY created_at, id",
        (start, end),
    ).fetchall()
    return rows_to_dicts(rows)


def count_attempts(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) AS n FROM payment_attempts").fetchone()["n"])


def attempt_time_bounds(conn: sqlite3.Connection) -> tuple[int, int] | None:
    row = conn.execute(
        "SELECT MIN(created_at) AS lo, MAX(created_at) AS hi FROM v_payment_attempts"
    ).fetchone()
    if row is None or row["lo"] is None:
        return None
    return int(row["lo"]), int(row["hi"])


# ---------------------------------------------------------------------------
# Segment statistics
# ---------------------------------------------------------------------------


def upsert_segment_stat(conn: sqlite3.Connection, stat: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO segments_stats
            (segment_key, window_start, attempts, failures, baseline_rate, p_value)
        VALUES (:segment_key, :window_start, :attempts, :failures, :baseline_rate, :p_value)
        ON CONFLICT(segment_key, window_start) DO UPDATE SET
            attempts = excluded.attempts,
            failures = excluded.failures,
            baseline_rate = excluded.baseline_rate,
            p_value = excluded.p_value
        """,
        stat,
    )


def segment_stats_for_key(conn: sqlite3.Connection, segment_key: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM segments_stats WHERE segment_key = ? ORDER BY window_start",
        (segment_key,),
    ).fetchall()
    return rows_to_dicts(rows)


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------


def insert_incident(conn: sqlite3.Connection, incident: dict[str, Any]) -> None:
    _insert(conn, "incidents", incident)


def get_incident(conn: sqlite3.Connection, incident_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
    return dict(row) if row else None


def open_incidents(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM incidents WHERE closed_at IS NULL ORDER BY opened_at"
    ).fetchall()
    return rows_to_dicts(rows)


def list_incidents(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM incidents ORDER BY opened_at, id").fetchall()
    return rows_to_dicts(rows)


def close_incident(conn: sqlite3.Connection, incident_id: str, closed_at: int) -> None:
    conn.execute(
        "UPDATE incidents SET closed_at = ?, status = 'closed' WHERE id = ?",
        (closed_at, incident_id),
    )


def set_incident_at_risk(conn: sqlite3.Connection, incident_id: str, amount: int) -> None:
    conn.execute("UPDATE incidents SET at_risk_amount = ? WHERE id = ?", (amount, incident_id))


def set_incident_scope(conn: sqlite3.Connection, incident_id: str, scope: Sequence[str]) -> None:
    conn.execute(
        "UPDATE incidents SET affected_scope_json = ? WHERE id = ?",
        (json.dumps(sorted(scope)), incident_id),
    )


def count_incidents(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) AS n FROM incidents").fetchone()["n"])


# ---------------------------------------------------------------------------
# Recovery cases, actions, escalations, comms. Written by M2; the readers exist now so the
# detector can compute at-risk revenue and the CLI can report.
# ---------------------------------------------------------------------------


def insert_case(conn: sqlite3.Connection, case: dict[str, Any]) -> None:
    _insert(conn, "recovery_cases", case)


def get_case(conn: sqlite3.Connection, case_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM recovery_cases WHERE id = ?", (case_id,)).fetchone()
    return dict(row) if row else None


def get_case_for_order(conn: sqlite3.Connection, order_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM recovery_cases WHERE order_id = ?", (order_id,)).fetchone()
    return dict(row) if row else None


def cases_for_incident(conn: sqlite3.Connection, incident_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM recovery_cases WHERE incident_id = ? ORDER BY id", (incident_id,)
    ).fetchall()
    return rows_to_dicts(rows)


def insert_action(conn: sqlite3.Connection, action: dict[str, Any]) -> None:
    _insert(conn, "actions", action)


def actions_for_incident(conn: sqlite3.Connection, incident_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM actions WHERE incident_id = ? ORDER BY id", (incident_id,)
    ).fetchall()
    return rows_to_dicts(rows)


def insert_escalation(conn: sqlite3.Connection, escalation: dict[str, Any]) -> None:
    _insert(conn, "escalations", escalation)


def pending_escalations(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM escalations WHERE decision IS NULL ORDER BY created_at"
    ).fetchall()
    return rows_to_dicts(rows)


def insert_comm(conn: sqlite3.Connection, comm: dict[str, Any]) -> None:
    _insert(conn, "customer_comms", comm)


def comms_count_for_customer(
    conn: sqlite3.Connection, customer_id: str, since: int
) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM customer_comms WHERE customer_id = ? AND sent_at >= ?",
        (customer_id, since),
    ).fetchone()
    return int(row["n"])


# ---------------------------------------------------------------------------
# Webhook events
# ---------------------------------------------------------------------------


def insert_webhook_event(conn: sqlite3.Connection, event: dict[str, Any]) -> bool:
    """Insert one event. Returns False when the event id was already stored.

    The unique primary key on event_id is the dedupe (security doc section 4). A duplicate is a
    no-op that reports itself, not an error.
    """
    try:
        _insert(conn, "webhook_events", event)
    except sqlite3.IntegrityError:
        return False
    return True


def get_webhook_event(conn: sqlite3.Connection, event_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM webhook_events WHERE event_id = ?", (event_id,)
    ).fetchone()
    return dict(row) if row else None


def mark_webhook_acted(conn: sqlite3.Connection, event_id: str) -> None:
    conn.execute("UPDATE webhook_events SET acted = 1 WHERE event_id = ?", (event_id,))


def count_webhook_events(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) AS n FROM webhook_events").fetchone()["n"])


def verified_webhook_events(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM webhook_events WHERE verified = 1 ORDER BY received_at, event_id"
    ).fetchall()
    return rows_to_dicts(rows)


# ---------------------------------------------------------------------------
# Checkout hints
# ---------------------------------------------------------------------------


def insert_checkout_hint(conn: sqlite3.Connection, hint: dict[str, Any]) -> None:
    _insert(conn, "checkout_hints", hint)


def active_checkout_hints(conn: sqlite3.Connection, now: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM checkout_hints WHERE active_from <= ? "
        "AND (active_to IS NULL OR active_to > ?)",
        (now, now),
    ).fetchall()
    return rows_to_dicts(rows)


# ---------------------------------------------------------------------------
# LLM cache
# ---------------------------------------------------------------------------


def get_llm_cache(conn: sqlite3.Connection, prompt_hash: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM llm_cache WHERE prompt_hash = ?", (prompt_hash,)
    ).fetchone()
    return dict(row) if row else None


def put_llm_cache(conn: sqlite3.Connection, entry: dict[str, Any]) -> None:
    _insert(conn, "llm_cache", entry, or_="OR REPLACE")


# ---------------------------------------------------------------------------
# GROUND TRUTH. Evaluation runner only (Architecture section 10: "The runner is the only code
# allowed to read ground truth"). Nothing in salvage/detect, salvage/diagnose, salvage/decide or
# salvage/execute may import from this section. The simulator writes it; the runner reads it.
# ---------------------------------------------------------------------------


def insert_sim_run(conn: sqlite3.Connection, run: dict[str, Any]) -> None:
    _insert(conn, "sim_runs", run)


def finish_sim_run(conn: sqlite3.Connection, run_id: str, finished_at: int, sim_end: int) -> None:
    conn.execute(
        "UPDATE sim_runs SET finished_at = ?, sim_end = ? WHERE run_id = ?",
        (finished_at, sim_end, run_id),
    )


def get_sim_run(conn: sqlite3.Connection, run_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM sim_runs WHERE run_id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def latest_sim_run(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM sim_runs ORDER BY started_at DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def insert_truth_attempt(conn: sqlite3.Connection, truth: dict[str, Any]) -> None:
    _insert(conn, "sim_truth_attempts", truth)


def insert_truth_attempts(conn: sqlite3.Connection, truths: Sequence[dict[str, Any]]) -> None:
    for truth in truths:
        insert_truth_attempt(conn, truth)


def insert_truth_incident(conn: sqlite3.Connection, truth: dict[str, Any]) -> None:
    _insert(conn, "sim_truth_incidents", truth)


def truth_incidents_for_run(conn: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM sim_truth_incidents WHERE run_id = ? ORDER BY start_ts", (run_id,)
    ).fetchall()
    return rows_to_dicts(rows)


def count_truth_attempts(conn: sqlite3.Connection, run_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM sim_truth_attempts WHERE run_id = ?", (run_id,)
    ).fetchone()
    return int(row["n"])
