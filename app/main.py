"""
SAP S/4HANA -> PostgreSQL Connector — Main entry point.

Runs the extraction workflow in three *stages*, each one committed on its own
(a checkpoint), so a SAP quota error half-way never throws away finished work:

  Stage 1  suppliers  (+ company, purch-org, text)
  Stage 2  purchase orders + items
  Stage 3  invoice headers + invoice-to-PO references

Every stage does:  fetch from SAP -> map -> integrity check (against this run's
data AND the database) -> upsert -> advance watermark -> update run log -> COMMIT.

Incremental mode (INCREMENTAL=true, the default)
  * a watermark per entity (table ``sync_state``) is sent to SAP as a
    ``$filter`` so only new / changed records are downloaded,
  * rows are upserted: new rows inserted, changed rows updated, identical
    rows left alone,
  * every update is recorded by a database trigger in ``change_log`` and every
    run in ``run_log`` (both tagged with the run id).

FULL_REFRESH=true ignores the watermarks for one run; INCREMENTAL=false gives
the old behaviour (always fetch from the start).
"""

import sys
from datetime import datetime, timedelta, timezone

import requests

# On Windows, stdout is cp1252 when redirected (``> file`` / ``| Out-File``) and
# crashes on any non-cp1252 character.  Force UTF-8 and never fail on printing.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from app.config import load_config
from app.sap_client import SAPClient, SAPQuotaExceeded
from app.db import get_connection
from app.integrity import enforce_integrity, MAX_EXAMPLES
from app import sync_state
from app.sync_state import ENTITY_SUPPLIER
from app.odata import chunked

from app.connectors.supplier_connector import fetch_all_suppliers_with_related
from app.connectors.purchase_order_connector import (
    fetch_all_pos_with_items, fetch_po_batch, fetch_purchase_order_items,
)
from app.connectors.invoice_connector import fetch_all_invoices_and_refs

from app.mapping.mappers import (
    map_supplier,
    map_supplier_company,
    map_supplier_purchasing_org,
    map_supplier_text,
    map_purchase_order,
    map_purchase_order_item,
    map_supplier_invoice,
    map_invoice_po_reference,
)

from app.repositories.repositories import (
    upsert_suppliers,
    upsert_supplier_companies,
    upsert_supplier_purchasing_orgs,
    upsert_supplier_texts,
    upsert_purchase_orders,
    upsert_purchase_order_items,
    upsert_supplier_invoices,
    upsert_invoice_po_references,
)


SEPARATOR = "=" * 60


def _print_header(title: str) -> None:
    print(f"\n{SEPARATOR}")
    print(f"  {title}")
    print(SEPARATOR)


# (table, upsert function, key in the "clean" dict) - in dependency order
STAGE_SUPPLIERS = [
    ("supplier", upsert_suppliers, "suppliers"),
    ("supplier_company", upsert_supplier_companies, "companies"),
    ("supplier_purchasing_org", upsert_supplier_purchasing_orgs, "purch_orgs"),
    ("supplier_text", upsert_supplier_texts, "texts"),
]
STAGE_ORDERS = [
    ("purchase_order", upsert_purchase_orders, "orders"),
    ("purchase_order_item", upsert_purchase_order_items, "items"),
]
STAGE_INVOICES = [
    ("supplier_invoice", upsert_supplier_invoices, "invoices"),
    ("invoice_po_reference", upsert_invoice_po_references, "po_refs"),
]
ALL_TABLES = STAGE_SUPPLIERS + STAGE_ORDERS + STAGE_INVOICES


def _map_raw(raw: dict) -> dict:
    """Map whatever raw SAP lists are present to model lists (missing -> [])."""
    g = lambda k: raw.get(k, [])  # noqa: E731
    return dict(
        suppliers=[map_supplier(p) for p in g("suppliers")],
        companies=[map_supplier_company(p.get("Supplier", ""), p) for p in g("companies")],
        purch_orgs=[map_supplier_purchasing_org(p.get("Supplier", ""), p) for p in g("purch_orgs")],
        texts=[map_supplier_text(p.get("Supplier", ""), p) for p in g("texts")],
        orders=[map_purchase_order(p) for p in g("orders")],
        items=[map_purchase_order_item(p) for p in g("items")],
        invoices=[map_supplier_invoice(p) for p in g("invoice_headers")],
        po_refs=[map_invoice_po_reference(p) for p in g("po_refs")],
    )


class _Run:
    """State shared by the stages of one run (stats / dropped rows for run_log)."""

    def __init__(self, conn, cur, sap, run_id: str, sc):
        self.conn, self.cur, self.sap, self.run_id, self.sc = conn, cur, sap, run_id, sc
        self.stats: dict[str, dict[str, int]] = {}
        self.dropped: dict[str, dict] = {}

    def save_stage(self, label: str, raw: dict, plan: list) -> None:
        """Map -> integrity (vs. this run AND the DB) -> upsert.  Caller commits."""
        models = _map_raw(raw)
        details: dict[str, list] = {}
        known = sync_state.load_known_keys(self.cur)
        clean, report = enforce_integrity(**models, known=known, details=details)

        if report:
            for reason, n in sorted(report.items()):
                print(f"  [FIX] {n:>5} x {reason}")
                d = self.dropped.setdefault(reason, {"count": 0, "examples": []})
                d["count"] += n
                d["examples"] = (d["examples"] + details.get(reason, []))[:MAX_EXAMPLES]
        else:
            print("  OK all rows are consistent with the foreign keys")

        for table, upsert_fn, key in plan:
            res = upsert_fn(self.cur, clean[key])
            t = self.stats.setdefault(table, {"inserted": 0, "updated": 0, "unchanged": 0})
            t["inserted"] += res.inserted
            t["updated"] += res.updated
            t["unchanged"] += res.unchanged
            print(f"  -> {table:<25}: {res.inserted} new, {res.updated} updated, "
                  f"{res.unchanged} unchanged")

    def checkpoint(self) -> None:
        """Write the run log and COMMIT - everything so far is now safe."""
        sync_state.update_run(self.cur, self.run_id, self.sap.request_count,
                              self.stats, self.dropped)
        self.conn.commit()


class _PoFilterUnsupported(Exception):
    """SAP rejected the PO date filter/ordering -> fall back to a plain full fetch."""


def _po_stage_resumable(ctx: "_Run") -> dict:
    """Stage 2+3 in resumable batches (incremental mode).

    One batch = next POs of a supplier group -> their items -> their invoice
    references/headers -> map/integrity/upsert -> advance the PO cursor of those
    suppliers -> COMMIT.  A quota error loses only the batch in flight; the
    cursors of finished batches are saved, so the next run continues from them.

    Per-supplier cursors (table ``supplier_po_cursor``) are what make this
    resumable.  Suppliers sharing the same cursor are fetched together (chunks of
    ``SAP_FILTER_CHUNK`` suppliers in one OR-filter).  ``PO_TOP`` is the budget
    of POs per *run*; the run simply stops there and the next one carries on.
    """
    sc, cur, sap, run_id = ctx.sc, ctx.cur, ctx.sap, ctx.run_id
    suppliers = sorted(sync_state.load_known_keys(cur)["suppliers"])
    cursors = {} if sc.full_refresh else sync_state.load_po_cursors(cur)

    groups: dict = {}
    for sid in suppliers:
        groups.setdefault(cursors.get(sid), []).append(sid)
    # never-synced suppliers first, then by cursor (oldest first)
    ordered = sorted(groups.items(),
                     key=lambda kv: (0,) if kv[0] is None else (1, kv[0][0], kv[0][1] or ""))
    chunks = [(cur_, chunk) for cur_, members in ordered for chunk in chunked(members, sc.filter_chunk)]
    never = len(groups.get(None, []))
    print(f"  {len(suppliers)} suppliers in the database ({never} never synced for POs), "
          f"{len(chunks)} supplier chunk(s)")
    print(f"  Budget this run: up to {sc.po_top} POs, in batches of {sc.po_batch}")

    remaining, batches, total_pos, next_chunk = sc.po_top, 0, 0, 0
    for idx, (cursor, chunk) in enumerate(chunks):
        next_chunk = idx
        while remaining > 0:
            want = min(sc.po_batch, remaining)
            t_fetch = datetime.now(timezone.utc).replace(tzinfo=None)
            try:
                rows = fetch_po_batch(sap, chunk, cursor, want, sc.page_size,
                                      sc.po_date_field, sc.po_date_type)
            except requests.HTTPError as exc:
                if batches == 0:
                    raise _PoFilterUnsupported(str(exc))
                print(f"  [WARN] PO request failed ({exc}); stopping the PO stage here. "
                      f"Finished batches are saved - the next run continues.")
                return {"pos": total_pos, "batches": batches, "pending": True}
            numbers = [r["PurchaseOrder"] for r in rows if r.get("PurchaseOrder")]
            items = (fetch_purchase_order_items(sap, numbers, sc.item_top, sc.page_size, sc.filter_chunk)
                     if numbers else [])
            if len(items) >= sc.item_top:
                print(f"  [WARN] ITEM_TOP ({sc.item_top}) reached in this batch - some items may be "
                      f"missing. Raise ITEM_TOP or lower PO_BATCH.")
            inv = (fetch_all_invoices_and_refs(sap, numbers, top=sc.invoice_top,
                                               page_size=sc.page_size, chunk_size=sc.filter_chunk)
                   if numbers else {"invoice_headers": [], "po_refs": []})

            # everything for this batch is fetched -> now save it atomically
            exhausted = len(rows) < want
            new_cursor = sync_state.max_cursor(rows, sc.po_date_field, "PurchaseOrder")
            if exhausted:
                # all POs after the cursor are loaded; future changes carry a newer
                # timestamp.  1 day margin covers clock differences with SAP.
                margin = t_fetch - timedelta(days=1)
                if new_cursor is None or new_cursor[0] < margin:
                    new_cursor = (margin, None)
            print(f"\n  Batch {batches + 1}: {len(rows)} POs, {len(items)} items, "
                  f"{len(inv['invoice_headers'])} invoice headers, {len(inv['po_refs'])} references "
                  f"(SAP calls so far: {sap.request_count})")
            raw = {"orders": rows, "items": items,
                   "invoice_headers": inv["invoice_headers"], "po_refs": inv["po_refs"]}
            ctx.save_stage("po-batch", raw, STAGE_ORDERS + STAGE_INVOICES)
            if new_cursor is not None:
                sync_state.set_po_cursors(cur, chunk, new_cursor[0], new_cursor[1], run_id)
            ctx.checkpoint()                                   # COMMIT = checkpoint
            batches += 1
            total_pos += len(rows)
            remaining -= len(rows)
            cursor = new_cursor or cursor
            if exhausted:
                break
        if remaining <= 0:
            next_chunk = idx + 1
            break
        next_chunk = idx + 1

    pending = sum(len(c) for _, c in chunks[next_chunk:])
    return {"pos": total_pos, "batches": batches, "pending": pending}


def _po_stage_legacy(ctx: "_Run", supplier_ids: list) -> list:
    """Stage 2 without cursors: fetch POs + items from the start (capped by PO_TOP).

    Used for INCREMENTAL=false and when SAP rejects the date filter.
    Returns the PO numbers fetched (for the invoice stage).
    """
    sc, sap = ctx.sc, ctx.sap
    raw_po: dict = {"orders": [], "items": []}
    try:
        raw_po = fetch_all_pos_with_items(
            sap, supplier_ids, top=sc.po_top, item_top=sc.item_top,
            page_size=sc.page_size, chunk_size=sc.filter_chunk,
        )
    except SAPQuotaExceeded as exc:
        partial = getattr(exc, "partial", None) or {}
        if partial.get("orders"):
            print(f"  [QUOTA] saving the {len(partial['orders'])} purchase orders fetched so far ...")
            ctx.save_stage("orders", partial, STAGE_ORDERS)
            ctx.checkpoint()
        raise
    print(f"  Fetched {len(raw_po['orders'])} purchase orders, {len(raw_po['items'])} items")
    print(f"  (SAP calls so far: {sap.request_count})")
    ctx.save_stage("orders", raw_po, STAGE_ORDERS)
    ctx.checkpoint()
    print("  OK Stage 2 committed")
    return sorted({po["PurchaseOrder"] for po in raw_po["orders"] if po.get("PurchaseOrder")})


def _invoice_stage_legacy(ctx: "_Run", po_numbers: list) -> None:
    """Stage 3 for a list of PO numbers (used after the legacy PO stage)."""
    sc, sap = ctx.sc, ctx.sap
    print(f"  Looking up invoice references for {len(po_numbers)} purchase orders")
    try:
        raw_inv = fetch_all_invoices_and_refs(
            sap, po_numbers, top=sc.invoice_top, page_size=sc.page_size, chunk_size=sc.filter_chunk,
        )
    except SAPQuotaExceeded as exc:
        partial = getattr(exc, "partial", None)
        if partial and partial.get("invoice_headers"):
            print(f"  [QUOTA] saving the {len(partial['invoice_headers'])} invoice headers fetched so far ...")
            ctx.save_stage("invoices", partial, STAGE_INVOICES)
            ctx.checkpoint()
        raise
    print(f"  Fetched {len(raw_inv['invoice_headers'])} invoice headers, "
          f"{len(raw_inv['po_refs'])} invoice-PO references")
    print(f"  Total SAP calls for this run: {sap.request_count}")
    ctx.save_stage("invoices", raw_inv, STAGE_INVOICES)
    ctx.checkpoint()
    print("  OK Stage 3 committed")


def run() -> None:
    # ------------------------------------------------------------------
    # Step 1 - Load configuration
    # ------------------------------------------------------------------
    _print_header("Step 1 - Loading configuration")
    config = load_config()
    sc = config.sap
    use_wm = sc.incremental and not sc.full_refresh   # send watermark filters?
    mode = "full" if not use_wm else "incremental"
    print(f"  SAP base URL : {sc.base_url}")
    print(f"  SAP auth mode: {sc.auth_mode}")
    print(f"  PostgreSQL   : {config.pg.user}@{config.pg.host}:{config.pg.port}/{config.pg.database}")
    print(f"  Paging/limits: page={sc.page_size}, filter-chunk={sc.filter_chunk}, "
          f"expand={sc.use_expand}, delay={sc.request_delay}s")
    print(f"  Mode         : {mode}"
          + ("" if sc.incremental else "  (INCREMENTAL=false: always fetches from the start)")
          + ("  (FULL_REFRESH: watermarks ignored this run)" if sc.incremental and sc.full_refresh else ""))

    # ------------------------------------------------------------------
    # Step 2 - Create clients, prepare incremental tables, start the run
    # ------------------------------------------------------------------
    _print_header("Step 2 - Connecting to SAP and PostgreSQL")
    sap = SAPClient(sc)
    conn = get_connection(config.pg)
    print("  OK SAP HTTP client ready")
    print("  OK PostgreSQL connection established")

    sync_state.ensure_schema(conn)          # sync_state / run_log / change_log + triggers
    stale = sync_state.reset_stale_cursors(conn)
    if stale:
        print(f"  [WARN] The data tables are empty but {' and '.join(stale)} existed - "
              f"reset, so everything is fetched again from the start.")
    run_id = sync_state.new_run_id()
    sync_state.start_run(conn, run_id, mode)  # also tags the session for the change-log trigger
    print(f"  OK Run id: {run_id}")

    status, error = "OK", None
    try:
        cur = conn.cursor()
        ctx = _Run(conn, cur, sap, run_id, sc)

        # ==================================================================
        # STAGE 1 - suppliers
        # ==================================================================
        _print_header("Stage 1 - Suppliers")
        sup_cur = sync_state.get_cursor(cur, ENTITY_SUPPLIER) if use_wm else None
        sup_wm, sup_key = sup_cur if sup_cur else (None, None)
        print(f"  Watermark ({sc.supplier_date_field}): "
              f"{(str(sup_wm) + (' / ' + sup_key if sup_key else '')) if sup_wm else 'none - fetching from the oldest'}")

        def _advance_supplier_wm(raw: dict) -> None:
            """Cursor = last (date, Supplier) fetched; only valid for oldest-first data."""
            if not sc.incremental or not raw.get("_ordered"):
                return
            new_cur = sync_state.max_cursor(raw["suppliers"], sc.supplier_date_field, "Supplier")
            if new_cur is not None:
                sync_state.set_cursor(cur, ENTITY_SUPPLIER, sc.supplier_date_field,
                                      new_cur[0], new_cur[1], run_id)
                print(f"  Supplier watermark -> {new_cur[0]} / {new_cur[1]}")

        try:
            raw_sup = fetch_all_suppliers_with_related(
                sap, top=sc.supplier_top, page_size=sc.page_size, use_expand=sc.use_expand,
                watermark=sup_wm, watermark_key=sup_key, date_field=sc.supplier_date_field,
                date_type=sc.supplier_date_type, ordered=sc.incremental,
            )
        except SAPQuotaExceeded as exc:
            partial = getattr(exc, "partial", None)
            if partial and partial.get("suppliers"):
                print(f"  [QUOTA] saving the {len(partial['suppliers'])} suppliers fetched so far ...")
                ctx.save_stage("suppliers", partial, STAGE_SUPPLIERS)
                _advance_supplier_wm(partial)
                ctx.checkpoint()
            raise

        print(f"  Fetched {len(raw_sup['suppliers'])} suppliers, {len(raw_sup['companies'])} company, "
              f"{len(raw_sup['purch_orgs'])} purchasing-org, {len(raw_sup['texts'])} text records")
        print(f"  (SAP calls so far: {sap.request_count})")
        ctx.save_stage("suppliers", raw_sup, STAGE_SUPPLIERS)
        _advance_supplier_wm(raw_sup)
        ctx.checkpoint()
        print("  OK Stage 1 committed")

        # ==================================================================
        # STAGE 2 (+3) - purchase orders, items, invoices
        # ==================================================================
        stored_suppliers = sorted(sync_state.load_known_keys(cur)["suppliers"])
        fetched_suppliers = sorted({s["Supplier"] for s in raw_sup["suppliers"] if s.get("Supplier")})
        run_legacy = not sc.incremental
        legacy_suppliers = fetched_suppliers

        if sc.incremental:
            _print_header("Stage 2 - Purchase orders, items & invoices (resumable batches)")
            try:
                summary = _po_stage_resumable(ctx)
                print(f"\n  OK {summary['pos']} POs in {summary['batches']} committed batch(es)")
                if summary["pending"]:
                    print(f"  [INFO] PO_TOP reached - {summary['pending']} supplier(s) still to be "
                          f"scanned. Nothing is lost: the next run continues from the saved cursors.")
            except _PoFilterUnsupported as exc:
                print(f"  [WARN] SAP rejected the PO date filter/ordering on '{sc.po_date_field}' ({exc}); "
                      f"falling back to a plain full fetch (no incremental saving for POs).")
                run_legacy, legacy_suppliers = True, stored_suppliers

        if run_legacy:
            _print_header("Stage 2 - Purchase orders & items")
            po_numbers = _po_stage_legacy(ctx, legacy_suppliers)
            _print_header("Stage 3 - Invoices & PO references")
            _invoice_stage_legacy(ctx, po_numbers)
        print(f"  Total SAP calls for this run: {sap.request_count}")

        # ------------------------------------------------------------------
        # Verification
        # ------------------------------------------------------------------
        _print_header("Verification")

        print("\n  Record counts in PostgreSQL:")
        for table_name, _, _ in ALL_TABLES:
            cur.execute(f"SELECT COUNT(*) FROM {table_name}")
            print(f"    {table_name:30s} : {cur.fetchone()[0]}")

        cur.execute("SELECT COUNT(*) FROM change_log WHERE run_id = %s", (run_id,))
        print(f"\n  Changes logged by this run (change_log): {cur.fetchone()[0]}")

        print("\n  Sample relationship verification:")
        cur.execute("""
            SELECT s.supplier, s.supplier_name,
                   COUNT(DISTINCT po.purchase_order) AS po_count
            FROM supplier s
            LEFT JOIN purchase_order po ON po.supplier = s.supplier
            GROUP BY s.supplier, s.supplier_name
            ORDER BY po_count DESC
            LIMIT 5
        """)
        print("    Top 5 suppliers by PO count:")
        for row in cur.fetchall():
            print(f"      Supplier {row[0]} ({row[1]}): {row[2]} POs")

        cur.execute("""
            SELECT poi.purchase_order, poi.purchase_order_item,
                   COUNT(ipr.supplier_invoice) AS ref_count
            FROM purchase_order_item poi
            LEFT JOIN invoice_po_reference ipr
                   ON ipr.purchase_order = poi.purchase_order
                  AND ipr.purchase_order_item = poi.purchase_order_item
            GROUP BY poi.purchase_order, poi.purchase_order_item
            HAVING COUNT(ipr.supplier_invoice) > 0
            ORDER BY ref_count DESC
            LIMIT 5
        """)
        print("    Top 5 PO items by invoice-reference count:")
        for row in cur.fetchall():
            print(f"      PO {row[0]} / Item {row[1]}: {row[2]} invoice refs")

        cur.close()

    except SAPQuotaExceeded as exc:
        conn.rollback()                       # drops only the unfinished stage
        status, error = "QUOTA", str(exc)
        raise
    except Exception as exc:
        conn.rollback()
        status, error = "FAILED", f"{type(exc).__name__}: {exc}"
        raise
    finally:
        try:
            sync_state.finish_run(conn, run_id, status, error)
        finally:
            conn.close()

    _print_header("Done")
    print("  SAP -> PostgreSQL extraction completed successfully.\n")


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)
    except SAPQuotaExceeded as exc:
        print(f"\n[QUOTA] {exc}")
        print("        Every stage that finished before the quota error is already saved")
        print("        (see run_log). Re-run after the quota resets - it continues from the watermarks.")
        sys.exit(2)
    except Exception as exc:
        print(f"\n[FATAL] {type(exc).__name__}: {exc}")
        sys.exit(1)
