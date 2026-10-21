"""
SAP S/4HANA -> PostgreSQL Connector — Main entry point.

Runs the complete extraction workflow:
  1. Load configuration
  2. Connect to SAP and PostgreSQL
  3. Fetch suppliers (+ company, purch-org, text)
  4. Fetch purchase orders and items
  5. Fetch invoice headers and invoice-to-PO references
  6. Map all records to Python models
  7. Enforce referential integrity (so FK constraints cannot fail the load)
  8. Persist in dependency order inside a single transaction
  9. Print record counts and sample verification queries

Nothing is written to PostgreSQL until *all* SAP data has been fetched, so a
SAP failure (e.g. quota exhausted) never leaves a half-filled database.
"""

import sys

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
from app.integrity import enforce_integrity

from app.connectors.supplier_connector import fetch_all_suppliers_with_related
from app.connectors.purchase_order_connector import fetch_all_pos_with_items
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
    insert_suppliers,
    insert_supplier_companies,
    insert_supplier_purchasing_orgs,
    insert_supplier_texts,
    insert_purchase_orders,
    insert_purchase_order_items,
    insert_supplier_invoices,
    insert_invoice_po_references,
)


SEPARATOR = "=" * 60


def _print_header(title: str) -> None:
    print(f"\n{SEPARATOR}")
    print(f"  {title}")
    print(SEPARATOR)


def run() -> None:
    # ------------------------------------------------------------------
    # Step 1 - Load configuration
    # ------------------------------------------------------------------
    _print_header("Step 1 - Loading configuration")
    config = load_config()
    print(f"  SAP base URL : {config.sap.base_url}")
    print(f"  SAP auth mode: {config.sap.auth_mode}")
    print(f"  PostgreSQL   : {config.pg.user}@{config.pg.host}:{config.pg.port}/{config.pg.database}")
    print(f"  Paging/limits: page={config.sap.page_size}, filter-chunk={config.sap.filter_chunk}, "
          f"expand={config.sap.use_expand}, delay={config.sap.request_delay}s")

    # ------------------------------------------------------------------
    # Step 2 - Create clients
    # ------------------------------------------------------------------
    _print_header("Step 2 - Connecting to SAP and PostgreSQL")
    sap = SAPClient(config.sap)
    conn = get_connection(config.pg)
    print("  OK SAP HTTP client ready")
    print("  OK PostgreSQL connection established")

    try:
        cur = conn.cursor()
        sc = config.sap

        # ------------------------------------------------------------------
        # Step 3 - Fetch suppliers
        # ------------------------------------------------------------------
        _print_header("Step 3 - Fetching suppliers")
        raw_supplier_data = fetch_all_suppliers_with_related(
            sap, top=sc.supplier_top, page_size=sc.page_size, use_expand=sc.use_expand
        )
        print(f"  Fetched {len(raw_supplier_data['suppliers'])} suppliers")
        print(f"  Fetched {len(raw_supplier_data['companies'])} supplier-company records")
        print(f"  Fetched {len(raw_supplier_data['purch_orgs'])} supplier-purchasing-org records")
        print(f"  Fetched {len(raw_supplier_data['texts'])} supplier-text records")
        print(f"  (SAP calls so far: {sap.request_count})")

        # ------------------------------------------------------------------
        # Step 4 - Fetch purchase orders and items
        # ------------------------------------------------------------------
        _print_header("Step 4 - Fetching purchase orders & items")
        supplier_ids = [
            s["Supplier"] for s in raw_supplier_data["suppliers"] if s.get("Supplier")
        ]
        raw_po_data = fetch_all_pos_with_items(
            sap, supplier_ids, top=sc.po_top, item_top=sc.item_top,
            page_size=sc.page_size, chunk_size=sc.filter_chunk,
        )
        print(f"  Fetched {len(raw_po_data['orders'])} purchase orders")
        print(f"  Fetched {len(raw_po_data['items'])} purchase order items")
        print(f"  (SAP calls so far: {sap.request_count})")

        # ------------------------------------------------------------------
        # Step 5 - Fetch invoices and PO references
        # ------------------------------------------------------------------
        _print_header("Step 5 - Fetching invoices & PO references")
        po_numbers = list({
            po["PurchaseOrder"] for po in raw_po_data["orders"] if po.get("PurchaseOrder")
        })
        raw_inv_data = fetch_all_invoices_and_refs(
            sap, po_numbers, top=sc.invoice_top,
            page_size=sc.page_size, chunk_size=sc.filter_chunk,
        )
        print(f"  Fetched {len(raw_inv_data['invoice_headers'])} invoice headers")
        print(f"  Fetched {len(raw_inv_data['po_refs'])} invoice-PO references")
        print(f"  Total SAP calls for this run: {sap.request_count}")

        # ------------------------------------------------------------------
        # Step 6 - Map to Python models
        # ------------------------------------------------------------------
        _print_header("Step 6 - Mapping to models")

        suppliers = [map_supplier(p) for p in raw_supplier_data["suppliers"]]
        companies = [map_supplier_company(p.get("Supplier", ""), p) for p in raw_supplier_data["companies"]]
        purch_orgs = [map_supplier_purchasing_org(p.get("Supplier", ""), p) for p in raw_supplier_data["purch_orgs"]]
        texts = [map_supplier_text(p.get("Supplier", ""), p) for p in raw_supplier_data["texts"]]
        orders = [map_purchase_order(p) for p in raw_po_data["orders"]]
        items = [map_purchase_order_item(p) for p in raw_po_data["items"]]
        invoices = [map_supplier_invoice(p) for p in raw_inv_data["invoice_headers"]]
        po_refs = [map_invoice_po_reference(p) for p in raw_inv_data["po_refs"]]

        print(f"  Mapped {len(suppliers)} suppliers, {len(companies)} supplier-company, "
              f"{len(purch_orgs)} supplier-purchasing-org, {len(texts)} supplier-text")
        print(f"  Mapped {len(orders)} purchase orders, {len(items)} items, "
              f"{len(invoices)} invoices, {len(po_refs)} invoice-PO references")

        # ------------------------------------------------------------------
        # Step 7 - Referential integrity
        # ------------------------------------------------------------------
        _print_header("Step 7 - Checking referential integrity")
        clean, report = enforce_integrity(
            suppliers, companies, purch_orgs, texts, orders, items, invoices, po_refs
        )
        if report:
            for reason, n in sorted(report.items()):
                print(f"  [FIX] {n:>5} x {reason}")
        else:
            print("  OK all rows are consistent with the foreign keys")

        # ------------------------------------------------------------------
        # Step 8 - Persist in dependency order
        # ------------------------------------------------------------------
        _print_header("Step 8 - Persisting to PostgreSQL")

        plan = [
            ("supplier", insert_suppliers, "suppliers"),
            ("supplier_company", insert_supplier_companies, "companies"),
            ("supplier_purchasing_org", insert_supplier_purchasing_orgs, "purch_orgs"),
            ("supplier_text", insert_supplier_texts, "texts"),
            ("purchase_order", insert_purchase_orders, "orders"),
            ("purchase_order_item", insert_purchase_order_items, "items"),
            ("supplier_invoice", insert_supplier_invoices, "invoices"),
            ("invoice_po_reference", insert_invoice_po_references, "po_refs"),
        ]
        for table, insert_fn, key in plan:
            rows = clean[key]
            inserted = insert_fn(cur, rows)
            existing = len(rows) - inserted
            note = f"  ({existing} already existed)" if existing else ""
            print(f"  -> {table:<25}: {inserted} new rows{note}")

        conn.commit()
        print("\n  OK Transaction committed successfully")

        # ------------------------------------------------------------------
        # Step 9 - Verify
        # ------------------------------------------------------------------
        _print_header("Step 9 - Verification")

        print("\n  Record counts in PostgreSQL:")
        for table_name, _, _ in plan:
            cur.execute(f"SELECT COUNT(*) FROM {table_name}")
            print(f"    {table_name:30s} : {cur.fetchone()[0]}")

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

    except Exception:
        conn.rollback()
        raise
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
        print("        Nothing was written to PostgreSQL. Re-run after the quota resets.")
        sys.exit(2)
    except Exception as exc:
        print(f"\n[FATAL] {type(exc).__name__}: {exc}")
        sys.exit(1)
