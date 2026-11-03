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
