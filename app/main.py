"""
SAP S/4HANA → PostgreSQL Connector — Main entry point.

Runs the complete happy-path extraction workflow:
  1. Load configuration
  2. Connect to SAP and PostgreSQL
  3. Fetch suppliers (+ company, purch-org, text)
  4. Fetch purchase orders and items
  5. Fetch invoice headers and invoice-to-PO references
  6. Map all records to Python models
  7. Persist in dependency order inside a single transaction
  8. Print record counts and sample verification queries
"""

import sys

from app.config import load_config
from app.sap_client import SAPClient
from app.db import get_connection

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
    # Step 1 — Load configuration
    # ------------------------------------------------------------------
    _print_header("Step 1 — Loading configuration")
    config = load_config()
    print(f"  SAP base URL : {config.sap.base_url}")
    print(f"  SAP auth mode: {config.sap.auth_mode}")
    print(f"  PostgreSQL   : {config.pg.user}@{config.pg.host}:{config.pg.port}/{config.pg.database}")

    # ------------------------------------------------------------------
    # Step 2 — Create clients
    # ------------------------------------------------------------------
    _print_header("Step 2 — Connecting to SAP and PostgreSQL")
    sap = SAPClient(config.sap)
    conn = get_connection(config.pg)
    print("  ✓ SAP HTTP client ready")
    print("  ✓ PostgreSQL connection established")

    try:
        cur = conn.cursor()

        # ------------------------------------------------------------------
        # Step 3 — Fetch suppliers
        # ------------------------------------------------------------------
        _print_header("Step 3 — Fetching suppliers")
        raw_supplier_data = fetch_all_suppliers_with_related(
            sap, top=config.sap.supplier_top
        )
        print(f"  Fetched {len(raw_supplier_data['suppliers'])} suppliers")
        print(f"  Fetched {len(raw_supplier_data['companies'])} supplier-company records")
        print(f"  Fetched {len(raw_supplier_data['purch_orgs'])} supplier-purchasing-org records")
        print(f"  Fetched {len(raw_supplier_data['texts'])} supplier-text records")

        # ------------------------------------------------------------------
        # Step 4 — Fetch purchase orders and items
        # ------------------------------------------------------------------
        _print_header("Step 4 — Fetching purchase orders & items")
        supplier_ids = [
            s["Supplier"]
            for s in raw_supplier_data["suppliers"]
            if s.get("Supplier")
        ]
        raw_po_data = fetch_all_pos_with_items(
            sap, supplier_ids, top=config.sap.po_top
        )
        print(f"  Fetched {len(raw_po_data['orders'])} purchase orders")
        print(f"  Fetched {len(raw_po_data['items'])} purchase order items")

        # ------------------------------------------------------------------
        # Step 5 — Fetch invoices and PO references
        # ------------------------------------------------------------------
        _print_header("Step 5 — Fetching invoices & PO references")
        po_numbers = list({
            po["PurchaseOrder"]
            for po in raw_po_data["orders"]
            if po.get("PurchaseOrder")
        })
        raw_inv_data = fetch_all_invoices_and_refs(
            sap, po_numbers, top=config.sap.invoice_top
        )
        print(f"  Fetched {len(raw_inv_data['invoice_headers'])} invoice headers")
        print(f"  Fetched {len(raw_inv_data['po_refs'])} invoice-PO references")

        # ------------------------------------------------------------------
        # Step 6 — Map to Python models
        # ------------------------------------------------------------------
        _print_header("Step 6 — Mapping to models")

        suppliers = [map_supplier(p) for p in raw_supplier_data["suppliers"]]
        companies = []
        for p in raw_supplier_data["companies"]:
            sid = p.get("Supplier", "")
            companies.append(map_supplier_company(sid, p))
        purch_orgs = []
        for p in raw_supplier_data["purch_orgs"]:
            sid = p.get("Supplier", "")
            purch_orgs.append(map_supplier_purchasing_org(sid, p))
        texts = []
        for p in raw_supplier_data["texts"]:
            sid = p.get("Supplier", "")
            texts.append(map_supplier_text(sid, p))

        orders = [map_purchase_order(p) for p in raw_po_data["orders"]]
        items = [map_purchase_order_item(p) for p in raw_po_data["items"]]

        invoices = [map_supplier_invoice(p) for p in raw_inv_data["invoice_headers"]]
        po_refs = [map_invoice_po_reference(p) for p in raw_inv_data["po_refs"]]

        print(f"  Mapped {len(suppliers)} suppliers")
        print(f"  Mapped {len(companies)} supplier-company records")
        print(f"  Mapped {len(purch_orgs)} supplier-purchasing-org records")
        print(f"  Mapped {len(texts)} supplier-text records")
        print(f"  Mapped {len(orders)} purchase orders")
        print(f"  Mapped {len(items)} purchase order items")
        print(f"  Mapped {len(invoices)} invoices")
        print(f"  Mapped {len(po_refs)} invoice-PO references")

        # ------------------------------------------------------------------
        # Step 7 — Persist in dependency order
        # ------------------------------------------------------------------
        _print_header("Step 7 — Persisting to PostgreSQL")

        n1 = insert_suppliers(cur, suppliers)
        print(f"  → supplier              : {n1} rows")

        n2 = insert_supplier_companies(cur, companies)
        print(f"  → supplier_company      : {n2} rows")

        n3 = insert_supplier_purchasing_orgs(cur, purch_orgs)
        print(f"  → supplier_purchasing_org: {n3} rows")

        n4 = insert_supplier_texts(cur, texts)
        print(f"  → supplier_text         : {n4} rows")

        n5 = insert_purchase_orders(cur, orders)
        print(f"  → purchase_order        : {n5} rows")

        n6 = insert_purchase_order_items(cur, items)
        print(f"  → purchase_order_item   : {n6} rows")

        n7 = insert_supplier_invoices(cur, invoices)
        print(f"  → supplier_invoice      : {n7} rows")

        n8 = insert_invoice_po_references(cur, po_refs)
        print(f"  → invoice_po_reference  : {n8} rows")

        conn.commit()
        print("\n  ✓ Transaction committed successfully")

        # ------------------------------------------------------------------
        # Step 8 — Verify
        # ------------------------------------------------------------------
        _print_header("Step 8 — Verification")

        verify_queries = [
            ("supplier", "SELECT COUNT(*) FROM supplier"),
            ("supplier_company", "SELECT COUNT(*) FROM supplier_company"),
            ("supplier_purchasing_org", "SELECT COUNT(*) FROM supplier_purchasing_org"),
            ("supplier_text", "SELECT COUNT(*) FROM supplier_text"),
            ("purchase_order", "SELECT COUNT(*) FROM purchase_order"),
            ("purchase_order_item", "SELECT COUNT(*) FROM purchase_order_item"),
            ("supplier_invoice", "SELECT COUNT(*) FROM supplier_invoice"),
            ("invoice_po_reference", "SELECT COUNT(*) FROM invoice_po_reference"),
        ]

        print("\n  Record counts in PostgreSQL:")
        for table_name, sql in verify_queries:
            cur.execute(sql)
            count = cur.fetchone()[0]
            print(f"    {table_name:30s} : {count}")

        # Relationship check: Suppliers → POs
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

        # Relationship check: PO → Items → Invoice refs
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
    print("  SAP → PostgreSQL extraction completed successfully.\n")


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)
    except Exception as exc:
        print(f"\n[FATAL] {exc}")
        sys.exit(1)
