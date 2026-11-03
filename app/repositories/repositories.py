"""
Repository layer — persists Python model objects into PostgreSQL.

Uses psycopg2 with parameterised queries and a real UPSERT:

    INSERT ... ON CONFLICT (key) DO UPDATE SET <non-key columns>
    WHERE <row> IS DISTINCT FROM <new row>

* a new row is inserted,
* an existing row is updated only if at least one value really changed
  (so re-runs do not rewrite identical rows, and the change-log trigger
  only fires for genuine changes),
* an identical row is left untouched.

All writes happen inside the caller's transaction (the caller commits).
"""

from dataclasses import asdict
from typing import NamedTuple
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
# Result type + generic helper
# ------------------------------------------------------------------

class UpsertResult(NamedTuple):
    """How many rows an upsert inserted / updated / left unchanged."""
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0

    def __add__(self, other: "UpsertResult") -> "UpsertResult":  # type: ignore[override]
        return UpsertResult(
            self.inserted + other.inserted,
            self.updated + other.updated,
            self.unchanged + other.unchanged,
        )

    @property
    def total(self) -> int:
        return self.inserted + self.updated + self.unchanged


_INSERTED, _UPDATED, _UNCHANGED = UpsertResult(1), UpsertResult(0, 1), UpsertResult(0, 0, 1)


def _upsert(cursor, table: str, obj, conflict_cols: list[str]) -> UpsertResult:
    """INSERT ... ON CONFLICT DO UPDATE ... WHERE <something changed>.

    ``RETURNING (xmax = 0)`` tells an insert (True) from an update (False);
    no row is returned when the existing row was identical.
    """
    data = asdict(obj)
    columns = list(data.keys())
    value_cols = [c for c in columns if c not in conflict_cols]
    placeholders = [f"%({c})s" for c in columns]
    conflict = ", ".join(conflict_cols)
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in value_cols)
    old_row = ", ".join(f"{table}.{c}" for c in value_cols)
    new_row = ", ".join(f"EXCLUDED.{c}" for c in value_cols)
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) "
        f"VALUES ({', '.join(placeholders)}) "
        f"ON CONFLICT ({conflict}) DO UPDATE SET {set_clause} "
        f"WHERE ({old_row}) IS DISTINCT FROM ({new_row}) "
        f"RETURNING (xmax = 0)"
    )
    cursor.execute(sql, data)
    row = cursor.fetchone()
    if row is None:
        return _UNCHANGED
    return _INSERTED if row[0] else _UPDATED


# ------------------------------------------------------------------
# Table-specific insert functions
# ------------------------------------------------------------------

def upsert_supplier(cursor, obj: Supplier) -> UpsertResult:
    return _upsert(cursor, "supplier", obj, ["supplier"])


def upsert_supplier_company(cursor, obj: SupplierCompany) -> UpsertResult:
    return _upsert(cursor, "supplier_company", obj, ["supplier", "company_code"])


def upsert_supplier_purchasing_org(cursor, obj: SupplierPurchasingOrg) -> UpsertResult:
    return _upsert(cursor, "supplier_purchasing_org", obj, ["supplier", "purchasing_organization"])


def upsert_supplier_text(cursor, obj: SupplierText) -> UpsertResult:
    return _upsert(cursor, "supplier_text", obj, ["supplier", "language", "text_type"])


def upsert_purchase_order(cursor, obj: PurchaseOrder) -> UpsertResult:
    return _upsert(cursor, "purchase_order", obj, ["purchase_order"])


def upsert_purchase_order_item(cursor, obj: PurchaseOrderItem) -> UpsertResult:
    return _upsert(cursor, "purchase_order_item", obj, ["purchase_order", "purchase_order_item"])


def upsert_supplier_invoice(cursor, obj: SupplierInvoice) -> UpsertResult:
    return _upsert(cursor, "supplier_invoice", obj, ["supplier_invoice", "fiscal_year"])


def upsert_invoice_po_reference(cursor, obj: InvoicePOReference) -> UpsertResult:
    return _upsert(
        cursor, "invoice_po_reference", obj,
        ["supplier_invoice", "fiscal_year", "purchase_order",
         "purchase_order_item", "supplier_invoice_item"],
    )


# ------------------------------------------------------------------
# Batch upsert helpers (for the main workflow) - return an UpsertResult
# ------------------------------------------------------------------

def upsert_suppliers(cursor, objs: list[Supplier]) -> UpsertResult:
    return sum((upsert_supplier(cursor, o) for o in objs), UpsertResult())


def upsert_supplier_companies(cursor, objs: list[SupplierCompany]) -> UpsertResult:
    return sum((upsert_supplier_company(cursor, o) for o in objs), UpsertResult())


def upsert_supplier_purchasing_orgs(cursor, objs: list[SupplierPurchasingOrg]) -> UpsertResult:
    return sum((upsert_supplier_purchasing_org(cursor, o) for o in objs), UpsertResult())


def upsert_supplier_texts(cursor, objs: list[SupplierText]) -> UpsertResult:
    return sum((upsert_supplier_text(cursor, o) for o in objs), UpsertResult())


def upsert_purchase_orders(cursor, objs: list[PurchaseOrder]) -> UpsertResult:
    return sum((upsert_purchase_order(cursor, o) for o in objs), UpsertResult())


def upsert_purchase_order_items(cursor, objs: list[PurchaseOrderItem]) -> UpsertResult:
    return sum((upsert_purchase_order_item(cursor, o) for o in objs), UpsertResult())


def upsert_supplier_invoices(cursor, objs: list[SupplierInvoice]) -> UpsertResult:
    return sum((upsert_supplier_invoice(cursor, o) for o in objs), UpsertResult())


def upsert_invoice_po_references(cursor, objs: list[InvoicePOReference]) -> UpsertResult:
    return sum((upsert_invoice_po_reference(cursor, o) for o in objs), UpsertResult())
