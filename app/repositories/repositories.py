"""
Repository layer — persists Python model objects into PostgreSQL.

Uses psycopg2 with parameterised queries and ON CONFLICT DO NOTHING
(upsert-safe for re-runs).  All writes happen inside a single
transaction that is committed by the caller.
"""

from dataclasses import asdict
from app.models import (
    Supplier,
    SupplierCompany,
    SupplierPurchasingOrg,
    SupplierText,
    PurchaseOrder,
    PurchaseOrderItem,
    SupplierInvoice,
    InvoicePOReference,
)


# ------------------------------------------------------------------
# Generic helper
# ------------------------------------------------------------------

def _insert(cursor, table: str, obj, conflict_cols: list[str]) -> int:
    """Build and execute an INSERT … ON CONFLICT DO NOTHING statement.

    Returns 1 if a row was inserted, 0 if it already existed.
    """
    data = asdict(obj)
    columns = list(data.keys())
    placeholders = [f"%({c})s" for c in columns]
    conflict = ", ".join(conflict_cols)
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) "
        f"VALUES ({', '.join(placeholders)}) "
        f"ON CONFLICT ({conflict}) DO NOTHING"
    )
    cursor.execute(sql, data)
    return cursor.rowcount


# ------------------------------------------------------------------
# Table-specific insert functions
# ------------------------------------------------------------------

def insert_supplier(cursor, obj: Supplier) -> int:
    return _insert(cursor, "supplier", obj, ["supplier"])


def insert_supplier_company(cursor, obj: SupplierCompany) -> int:
    return _insert(cursor, "supplier_company", obj, ["supplier", "company_code"])


def insert_supplier_purchasing_org(cursor, obj: SupplierPurchasingOrg) -> int:
    return _insert(cursor, "supplier_purchasing_org", obj, ["supplier", "purchasing_organization"])


def insert_supplier_text(cursor, obj: SupplierText) -> int:
    return _insert(cursor, "supplier_text", obj, ["supplier", "language", "text_type"])


def insert_purchase_order(cursor, obj: PurchaseOrder) -> int:
    return _insert(cursor, "purchase_order", obj, ["purchase_order"])


def insert_purchase_order_item(cursor, obj: PurchaseOrderItem) -> int:
    return _insert(cursor, "purchase_order_item", obj, ["purchase_order", "purchase_order_item"])


def insert_supplier_invoice(cursor, obj: SupplierInvoice) -> int:
    return _insert(cursor, "supplier_invoice", obj, ["supplier_invoice", "fiscal_year"])


def insert_invoice_po_reference(cursor, obj: InvoicePOReference) -> int:
    return _insert(
        cursor, "invoice_po_reference", obj,
        ["supplier_invoice", "fiscal_year", "purchase_order",
         "purchase_order_item", "supplier_invoice_item"],
    )


# ------------------------------------------------------------------
# Batch insert helpers (for the main workflow) - return rows actually inserted
# ------------------------------------------------------------------

def insert_suppliers(cursor, objs: list[Supplier]) -> int:
    return sum(insert_supplier(cursor, o) for o in objs)


def insert_supplier_companies(cursor, objs: list[SupplierCompany]) -> int:
    return sum(insert_supplier_company(cursor, o) for o in objs)


def insert_supplier_purchasing_orgs(cursor, objs: list[SupplierPurchasingOrg]) -> int:
    return sum(insert_supplier_purchasing_org(cursor, o) for o in objs)


def insert_supplier_texts(cursor, objs: list[SupplierText]) -> int:
    return sum(insert_supplier_text(cursor, o) for o in objs)


def insert_purchase_orders(cursor, objs: list[PurchaseOrder]) -> int:
    return sum(insert_purchase_order(cursor, o) for o in objs)


def insert_purchase_order_items(cursor, objs: list[PurchaseOrderItem]) -> int:
    return sum(insert_purchase_order_item(cursor, o) for o in objs)


def insert_supplier_invoices(cursor, objs: list[SupplierInvoice]) -> int:
    return sum(insert_supplier_invoice(cursor, o) for o in objs)


def insert_invoice_po_references(cursor, objs: list[InvoicePOReference]) -> int:
    return sum(insert_invoice_po_reference(cursor, o) for o in objs)
