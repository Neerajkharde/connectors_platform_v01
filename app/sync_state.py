"""
Bookkeeping for incremental sync (all of it lives in PostgreSQL):

* ``sync_state``  - one watermark per entity ("loaded everything up to X")
* ``run_log``     - what each run did (counts, dropped rows, status)
* ``app.run_id``  - session setting read by the change-log trigger, so every
                    logged change carries the run that caused it
* known keys      - keys already stored in the DB, used by the integrity check
                    so children of an earlier run's parents are not dropped
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from app.mapping.mappers import _timestamp as parse_sap_timestamp

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "incremental.sql"

# entity names used in sync_state
ENTITY_SUPPLIER = "supplier"
ENTITY_PO = "purchase_order"


# ------------------------------------------------------------------
# Schema
# ------------------------------------------------------------------

def ensure_schema(conn) -> None:
    """Create sync_state / run_log / change_log and the triggers (idempotent)."""
    with conn.cursor() as cur:
        cur.execute(SQL_FILE.read_text(encoding="utf-8"))
    conn.commit()


def reset_stale_cursors(conn) -> list[str]:
    """Forget cursors that claim data which is no longer in the tables.

    Cursors say "everything up to here is loaded".  If someone truncated or
    re-created the data tables, that claim is false and the missing rows would
    never be fetched again.  Returns what was reset (for a log message).
    """
    reset = []
    with conn.cursor() as cur:
        cur.execute("SELECT NOT EXISTS (SELECT 1 FROM supplier)")
        no_suppliers = cur.fetchone()[0]
        cur.execute("SELECT NOT EXISTS (SELECT 1 FROM purchase_order)")
        no_orders = cur.fetchone()[0]
        if no_suppliers:
            cur.execute("DELETE FROM sync_state")
            if cur.rowcount:
                reset.append("supplier watermark")
        if no_suppliers or no_orders:
            cur.execute("DELETE FROM supplier_po_cursor")
            if cur.rowcount:
                reset.append("PO cursors")
    conn.commit()
    return reset


# ------------------------------------------------------------------
# Watermarks
# ------------------------------------------------------------------

def get_watermark(cur, entity: str) -> Optional[datetime]:
    cur.execute("SELECT last_value FROM sync_state WHERE entity = %s", (entity,))
    row = cur.fetchone()
    return row[0] if row else None


def set_watermark(cur, entity: str, field: str, value: datetime, run_id: str) -> None:
    """Store ``value``; the watermark can only move forward, never back."""
    cur.execute(
        """
        INSERT INTO sync_state (entity, watermark_field, last_value, last_run_id, updated_at)
        VALUES (%s, %s, %s, %s, now())
        ON CONFLICT (entity) DO UPDATE
           SET watermark_field = EXCLUDED.watermark_field,
               last_value      = GREATEST(sync_state.last_value, EXCLUDED.last_value),
               last_run_id     = EXCLUDED.last_run_id,
               updated_at      = now()
        """,
        (entity, field, value, run_id),
    )


Cursor = tuple  # (datetime, key | None)


def get_cursor(cur, entity: str) -> Optional[Cursor]:
    """``(value, key)`` of an entity, or None if never synced (key may be None)."""
    cur.execute("SELECT last_value, last_key FROM sync_state WHERE entity = %s", (entity,))
    row = cur.fetchone()
    return (row[0], row[1]) if row and row[0] is not None else None


def set_cursor(cur, entity: str, field: str, value: datetime, key: Optional[str], run_id: str) -> None:
    """Store ``(value, key)``; a cursor only ever moves forward."""
    cur.execute(
        """
        INSERT INTO sync_state (entity, watermark_field, last_value, last_key, last_run_id, updated_at)
        VALUES (%s, %s, %s, %s, %s, now())
        ON CONFLICT (entity) DO UPDATE
           SET watermark_field = EXCLUDED.watermark_field,
               last_value = EXCLUDED.last_value, last_key = EXCLUDED.last_key,
               last_run_id = EXCLUDED.last_run_id, updated_at = now()
         WHERE sync_state.last_value IS NULL
            OR (EXCLUDED.last_value, COALESCE(EXCLUDED.last_key, ''))
             > (sync_state.last_value, COALESCE(sync_state.last_key, ''))
        """,
        (entity, field, value, key, run_id),
    )


def max_cursor(rows: Iterable[dict], field: str, key_field: str) -> Optional[Cursor]:
    """Highest ``(field value, key)`` over raw SAP rows - the last row in (field, key) order."""
    best = None
    for row in rows:
        ts = parse_sap_timestamp(row.get(field))
        if ts is None:
            continue
        cand = (ts, row.get(key_field) or "")
        if best is None or cand > best:
            best = cand
    return (best[0], best[1] or None) if best else None


def load_po_cursors(cur) -> dict:
    """supplier -> (value, key) for every supplier whose POs were loaded before."""
    cur.execute("SELECT supplier, last_value, last_key FROM supplier_po_cursor")
    return {r[0]: (r[1], r[2]) for r in cur.fetchall()}


def set_po_cursors(cur, suppliers: list, value: datetime, key: Optional[str], run_id: str) -> None:
    """Move the PO cursor of all ``suppliers`` forward to ``(value, key)``."""
    if not suppliers:
        return
    cur.execute(
        """
        INSERT INTO supplier_po_cursor (supplier, last_value, last_key, last_run_id, updated_at)
        SELECT s, %s, %s, %s, now() FROM unnest(%s::text[]) AS s
        ON CONFLICT (supplier) DO UPDATE
           SET last_value = EXCLUDED.last_value, last_key = EXCLUDED.last_key,
               last_run_id = EXCLUDED.last_run_id, updated_at = now()
         WHERE (EXCLUDED.last_value, COALESCE(EXCLUDED.last_key, ''))
             > (supplier_po_cursor.last_value, COALESCE(supplier_po_cursor.last_key, ''))
        """,
        (value, key, run_id, list(suppliers)),
    )


def max_field_value(rows: Iterable[dict], field: str) -> Optional[datetime]:
    """Highest value of ``field`` over raw SAP rows (None if the field is absent)."""
    best = None
    for row in rows:
        ts = parse_sap_timestamp(row.get(field))
        if ts is not None and (best is None or ts > best):
            best = ts
    return best


# ------------------------------------------------------------------
# Run log + run id for the change-log trigger
# ------------------------------------------------------------------

def new_run_id() -> str:
    return str(uuid.uuid4())


def start_run(conn, run_id: str, mode: str) -> None:
    """Insert the run_log row (committed right away) and tag the session."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO run_log (run_id, mode) VALUES (%s, %s)", (run_id, mode)
        )
        # is_local=false -> lasts for the whole session, so it survives the
        # per-stage commits (SET LOCAL would be reset by every commit).
        cur.execute("SELECT set_config('app.run_id', %s, false)", (run_id,))
    conn.commit()


def update_run(cur, run_id: str, sap_calls: int, stats: dict, dropped: dict) -> None:
    cur.execute(
        "UPDATE run_log SET sap_calls = %s, stats = %s::jsonb, dropped = %s::jsonb "
        "WHERE run_id = %s",
        (sap_calls, json.dumps(stats), json.dumps(dropped), run_id),
    )


def finish_run(conn, run_id: str, status: str, error: str | None = None) -> None:
    """Close the run_log row. Call after rollback/commit - uses its own commit."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE run_log SET finished_at = now(), status = %s, error = %s "
            "WHERE run_id = %s",
            (status, error, run_id),
        )
    conn.commit()


# ------------------------------------------------------------------
# Keys that already exist in the database (for the integrity check)
# ------------------------------------------------------------------

def load_known_keys(cur) -> dict:
    """Keys already stored in PostgreSQL, grouped by what children point at."""
    cur.execute("SELECT supplier FROM supplier")
    suppliers = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT purchase_order FROM purchase_order")
    orders = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT purchase_order, purchase_order_item FROM purchase_order_item")
    items = {(r[0], r[1]) for r in cur.fetchall()}
    cur.execute("SELECT supplier_invoice, fiscal_year FROM supplier_invoice")
    invoices = {(r[0], r[1]) for r in cur.fetchall()}
    return {"suppliers": suppliers, "orders": orders, "items": items, "invoices": invoices}
