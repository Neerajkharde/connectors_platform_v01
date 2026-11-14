"""
FastAPI backend for the SAP S/4HANA → PostgreSQL Connector Web Dashboard.

Provides REST API endpoints for:
  - Health check and system status
  - Connector metadata (which SAP connectors exist and what they do)
  - Database table browsing (list tables, view schema, paginated records)
  - SAP entity metadata (entities, fields, mandatory/optional classification)
  - Data extraction (trigger extraction for selected entities and fields)
  - Extraction history (run log, change log)
"""

import asyncio
import json
import math
import traceback
import uuid
from contextlib import contextmanager
from dataclasses import asdict, fields as dc_fields
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import load_config, AppConfig
from app.db import get_connection
from app.models import (
    Supplier, SupplierCompany, SupplierPurchasingOrg, SupplierText,
    PurchaseOrder, PurchaseOrderItem, SupplierInvoice, InvoicePOReference,
)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="SAP-PostgreSQL Connector API",
    description="Backend API for the SAP S/4HANA → PostgreSQL data integration dashboard.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg() -> AppConfig:
    """Load config each time so .env changes are picked up on restart."""
    return load_config()


@contextmanager
def _db():
    """Yield a psycopg2 connection that is closed on exit."""
    conn = get_connection(_cfg().pg)
    try:
        yield conn
    finally:
        conn.close()


def _json_safe(value: Any) -> Any:
    """Make a value JSON-serialisable."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _row_to_dict(cursor, row) -> dict:
    """Convert a psycopg2 row to a dict using the cursor description."""
    return {
        desc[0]: _json_safe(val)
        for desc, val in zip(cursor.description, row)
    }


# ---------------------------------------------------------------------------
# Static metadata: table schema information, SAP entity definitions,
# connector descriptions, field descriptions
# ---------------------------------------------------------------------------

# The 8 data tables in dependency order
TABLE_NAMES = [
    "supplier",
    "supplier_company",
    "supplier_purchasing_org",
    "supplier_text",
    "purchase_order",
    "purchase_order_item",
    "supplier_invoice",
    "invoice_po_reference",
]

TABLE_LABELS = {
    "supplier": "Supplier",
    "supplier_company": "Supplier Company",
    "supplier_purchasing_org": "Supplier Purchasing Org",
    "supplier_text": "Supplier Text",
    "purchase_order": "Purchase Order",
    "purchase_order_item": "Purchase Order Item",
    "supplier_invoice": "Supplier Invoice",
    "invoice_po_reference": "Invoice PO Reference",
}

TABLE_DESCRIPTIONS = {
    "supplier": "Master data for SAP suppliers/vendors. Each row represents a unique business partner registered as a supplier in SAP S/4HANA.",
    "supplier_company": "Company code assignments for each supplier. Links a supplier to the company codes (legal entities) they do business with.",
    "supplier_purchasing_org": "Purchasing organization assignments for each supplier. Links a supplier to the purchasing organizations that manage procurement with them.",
    "supplier_text": "Long text notes and descriptions attached to suppliers, stored per language and text type.",
    "purchase_order": "Purchase order headers from SAP S/4HANA. Each row is one PO document with its metadata, status flags, and organizational assignments.",
    "purchase_order_item": "Line items within purchase orders. Each row is one item on a PO, with material, quantity, price, and account assignment details.",
    "supplier_invoice": "Supplier invoice headers from SAP S/4HANA. Each row is one invoice document received from a supplier.",
    "invoice_po_reference": "Links between supplier invoice items and purchase order items. Shows which PO items each invoice line references.",
}

# Primary key columns per table
TABLE_PKS = {
    "supplier": ["supplier"],
    "supplier_company": ["supplier", "company_code"],
    "supplier_purchasing_org": ["supplier", "purchasing_organization"],
    "supplier_text": ["supplier", "language", "text_type"],
    "purchase_order": ["purchase_order"],
    "purchase_order_item": ["purchase_order", "purchase_order_item"],
    "supplier_invoice": ["supplier_invoice", "fiscal_year"],
    "invoice_po_reference": ["supplier_invoice", "fiscal_year", "purchase_order",
                              "purchase_order_item", "supplier_invoice_item"],
}

# Foreign key definitions: column -> {referenced_table, referenced_column}
TABLE_FKS: dict[str, dict[str, dict]] = {
    "supplier": {},
    "supplier_company": {
        "supplier": {"referenced_table": "supplier", "referenced_column": "supplier"},
    },
    "supplier_purchasing_org": {
        "supplier": {"referenced_table": "supplier", "referenced_column": "supplier"},
    },
    "supplier_text": {
        "supplier": {"referenced_table": "supplier", "referenced_column": "supplier"},
    },
    "purchase_order": {
        "supplier": {"referenced_table": "supplier", "referenced_column": "supplier"},
    },
    "purchase_order_item": {
        "purchase_order": {"referenced_table": "purchase_order", "referenced_column": "purchase_order"},
    },
    "supplier_invoice": {
        "supplier": {"referenced_table": "supplier", "referenced_column": "supplier"},
        "purchase_order": {"referenced_table": "purchase_order", "referenced_column": "purchase_order"},
    },
    "invoice_po_reference": {
        "supplier_invoice": {"referenced_table": "supplier_invoice", "referenced_column": "supplier_invoice"},
        "fiscal_year": {"referenced_table": "supplier_invoice", "referenced_column": "fiscal_year"},
        "purchase_order": {"referenced_table": "purchase_order_item", "referenced_column": "purchase_order"},
        "purchase_order_item": {"referenced_table": "purchase_order_item", "referenced_column": "purchase_order_item"},
    },
}

# Model class per table (for field introspection)
TABLE_MODELS = {
    "supplier": Supplier,
    "supplier_company": SupplierCompany,
    "supplier_purchasing_org": SupplierPurchasingOrg,
    "supplier_text": SupplierText,
    "purchase_order": PurchaseOrder,
    "purchase_order_item": PurchaseOrderItem,
    "supplier_invoice": SupplierInvoice,
    "invoice_po_reference": InvoicePOReference,
}

# Human-readable field descriptions mapping SAP fields to business meaning
FIELD_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "supplier": {
        "supplier": "SAP supplier number (A_Supplier key). Unique 10-character vendor ID.",
        "supplier_name": "Short name of the supplier (SupplierName).",
        "supplier_full_name": "Full legal name of the supplier (SupplierFullName).",
        "supplier_account_group": "Account group code controlling master data fields (SupplierAccountGroup).",
        "alternative_payee_account_number": "Alternate payee vendor number if payments go elsewhere.",
        "authorization_group": "Authorization group for access control.",
        "business_partner_pan_number": "PAN (tax) number of the business partner.",
        "customer": "If this supplier is also a customer, the customer number.",
        "payment_is_blocked_for_supplier": "Whether outgoing payments are blocked for this supplier.",
        "posting_is_blocked": "Whether accounting postings are blocked.",
        "purchasing_is_blocked": "Whether purchasing transactions are blocked.",
        "vat_registration": "VAT registration number of the supplier.",
        "deletion_indicator": "Whether the supplier is marked for deletion in SAP.",
        "created_by_user": "SAP user who created the master record.",
        "creation_date": "Date the supplier master record was created in SAP (CreationDate).",
        "last_change_date_time": "Timestamp of the last change to the supplier record.",
    },
    "supplier_company": {
        "supplier": "Parent supplier number (FK → supplier).",
        "company_code": "SAP company code (4-char legal entity identifier).",
        "company_name": "Name of the company code.",
        "company_address": "Address of the company code.",
        "deletion_indicator": "Marked for deletion.",
        "created_by_user": "SAP user who created the record.",
        "creation_date": "Record creation date.",
        "last_change_date_time": "Last change timestamp.",
    },
    "supplier_purchasing_org": {
        "supplier": "Parent supplier number (FK → supplier).",
        "purchasing_organization": "SAP purchasing organization code.",
        "purchasing_org_name": "Name of the purchasing organization.",
        "deletion_indicator": "Marked for deletion.",
        "created_by_user": "SAP user who created the record.",
        "creation_date": "Record creation date.",
        "last_change_date_time": "Last change timestamp.",
    },
    "supplier_text": {
        "supplier": "Parent supplier number (FK → supplier).",
        "language": "Language key (e.g. 'EN', 'DE').",
        "text_type": "Text type identifier (e.g. long text ID).",
        "text": "The actual text content (can be long).",
        "deletion_indicator": "Marked for deletion.",
        "created_by_user": "SAP user who created the record.",
        "creation_date": "Record creation date.",
        "last_change_date_time": "Last change timestamp.",
    },
    "purchase_order": {
        "purchase_order": "SAP purchase order number (PurchaseOrder key).",
        "supplier": "Vendor/supplier on the PO (FK → supplier).",
        "purchase_order_type": "PO document type (e.g. NB = standard, FO = framework).",
        "purchase_order_subtype": "PO subtype code.",
        "purchasing_document_origin": "Origin of the purchasing document.",
        "purchasing_document_process_code": "Process code for the document.",
        "created_by_user": "SAP user who created the PO.",
        "creation_date": "Date the PO was created.",
        "purchase_order_date": "Document date of the PO.",
        "last_change_date_time": "Timestamp of the last change (LastChangeDateTime).",
        "validity_start_date": "Validity period start date.",
        "validity_end_date": "Validity period end date.",
        "msg_on_goods_receipt_is_required": "Whether a message is required on goods receipt.",
        "company_code": "Company code for the PO.",
        "purchasing_organization": "Purchasing organization for the PO.",
        "document_currency": "Currency of the PO document.",
        "deletion_indicator": "Whether the PO is marked for deletion.",
        "purchase_order_is_blocked": "Whether the PO is blocked.",
        "invoices_is_blocked": "Whether invoicing is blocked for this PO.",
        "goods_receipt_is_blocked": "Whether goods receipt is blocked.",
        "overall_release_status": "Release status of the PO.",
    },
    "purchase_order_item": {
        "purchase_order": "Parent PO number (FK → purchase_order).",
        "purchase_order_item": "Line item number within the PO.",
        "material": "Material/product number.",
        "short_text": "Item description text.",
        "order_quantity": "Ordered quantity.",
        "order_unit": "Unit of measure for the order quantity.",
        "net_price_amount": "Net price per unit.",
        "net_price_unit": "Price unit.",
        "item_category": "Item category (e.g. standard, limit).",
        "deletion_indicator": "Whether the item is marked for deletion.",
        "goods_receipt_is_expected": "Whether a goods receipt is expected.",
        "invoices_expected": "Whether an invoice is expected for this item.",
        "plant": "Receiving plant.",
        "storage_location": "Storage location within the plant.",
        "account_assignment_category": "Account assignment category (e.g. K = cost center).",
        "cost_center": "Cost center for the item.",
        "wbs_account": "WBS (Work Breakdown Structure) element.",
        "material_group": "Material group classification.",
        "created_by_user": "SAP user who created the item.",
        "creation_date": "Item creation date.",
        "last_change_date_time": "Last change timestamp.",
    },
    "supplier_invoice": {
        "supplier_invoice": "SAP supplier invoice document number.",
        "fiscal_year": "Fiscal year of the invoice.",
        "supplier": "Supplier who sent the invoice (FK → supplier).",
        "purchase_order": "Related purchase order (FK → purchase_order).",
        "company_code": "Company code that received the invoice.",
        "document_date": "Date on the invoice document.",
        "posting_date": "Accounting posting date.",
        "invoicing_party": "The party that issued the invoice (vendor number).",
        "document_currency": "Currency of the invoice.",
        "invoice_gross_amount": "Gross amount of the invoice.",
        "invoice_is_cancelled": "Whether the invoice has been cancelled/reversed.",
        "overall_invoice_status": "Overall processing status of the invoice.",
        "created_by_user": "SAP user who entered the invoice.",
        "creation_date": "Invoice entry date.",
        "last_change_date_time": "Last change timestamp.",
    },
    "invoice_po_reference": {
        "supplier_invoice": "Invoice document number (FK → supplier_invoice).",
        "fiscal_year": "Fiscal year (FK → supplier_invoice).",
        "purchase_order": "Referenced PO number (FK → purchase_order_item).",
        "purchase_order_item": "Referenced PO item number (FK → purchase_order_item).",
        "supplier_invoice_item": "Invoice line item number.",
        "referenced_amount": "Amount referenced from the PO item on this invoice line.",
        "referenced_quantity": "Quantity referenced from the PO item.",
        "document_currency": "Currency of the referenced amount.",
        "deletion_indicator": "Marked for deletion.",
        "created_by_user": "SAP user who created the reference.",
        "creation_date": "Reference creation date.",
        "last_change_date_time": "Last change timestamp.",
    },
}

# SAP entity definitions: entities the backend can extract, with their
# SAP API, OData version, and fields classified as mandatory or optional.
# "mandatory" = primary key columns that MUST always be extracted.
# "optional"  = every other column that can be toggled on/off.

SAP_ENTITIES = [
    {
        "id": "supplier",
        "name": "A_Supplier",
        "label": "Supplier Master",
        "description": "SAP Business Partner – Supplier master data including company and purchasing org assignments, plus long texts. Extracted from the A_Supplier OData V2 API with $expand for sub-entities.",
        "sap_api": "A_Supplier (OData V2 / XML-Atom)",
        "tables": ["supplier", "supplier_company", "supplier_purchasing_org", "supplier_text"],
        "mandatory_fields": ["supplier"],
        "optional_fields": [
            "supplier_name", "supplier_full_name", "supplier_account_group",
            "alternative_payee_account_number", "authorization_group",
            "business_partner_pan_number", "customer",
            "payment_is_blocked_for_supplier", "posting_is_blocked",
            "purchasing_is_blocked", "vat_registration", "deletion_indicator",
            "created_by_user", "creation_date", "last_change_date_time",
        ],
    },
    {
        "id": "purchase_order",
        "name": "PurchaseOrder",
        "label": "Purchase Order",
        "description": "Purchase order headers from the SAP Purchase Order API. Extracted via OData V4 JSON with resumable batch processing and per-supplier cursors.",
        "sap_api": "PurchaseOrder (OData V4 / JSON)",
        "tables": ["purchase_order"],
        "mandatory_fields": ["purchase_order"],
        "optional_fields": [
            "supplier", "purchase_order_type", "purchase_order_subtype",
            "purchasing_document_origin", "purchasing_document_process_code",
            "created_by_user", "creation_date", "purchase_order_date",
            "last_change_date_time", "validity_start_date", "validity_end_date",
            "msg_on_goods_receipt_is_required", "company_code",
            "purchasing_organization", "document_currency", "deletion_indicator",
            "purchase_order_is_blocked", "invoices_is_blocked",
            "goods_receipt_is_blocked", "overall_release_status",
        ],
    },
    {
        "id": "purchase_order_item",
        "name": "PurchaseOrderItem",
        "label": "Purchase Order Item",
        "description": "Line items of purchase orders. Fetched for each batch of POs via OData V4 JSON. Contains material, quantity, pricing, and account assignment details.",
        "sap_api": "PurchaseOrderItem (OData V4 / JSON)",
        "tables": ["purchase_order_item"],
        "mandatory_fields": ["purchase_order", "purchase_order_item"],
        "optional_fields": [
            "material", "short_text", "order_quantity", "order_unit",
            "net_price_amount", "net_price_unit", "item_category",
            "deletion_indicator", "goods_receipt_is_expected", "invoices_expected",
            "plant", "storage_location", "account_assignment_category",
            "cost_center", "wbs_account", "material_group",
            "created_by_user", "creation_date", "last_change_date_time",
        ],
    },
    {
        "id": "supplier_invoice",
        "name": "A_SupplierInvoice",
        "label": "Supplier Invoice",
        "description": "Supplier invoice headers from the Supplier Invoice Process API. Fetched by composite key (invoice number + fiscal year) via OData V2.",
        "sap_api": "A_SupplierInvoice (OData V2 / XML-Atom)",
        "tables": ["supplier_invoice"],
        "mandatory_fields": ["supplier_invoice", "fiscal_year"],
        "optional_fields": [
            "supplier", "purchase_order", "company_code",
            "document_date", "posting_date", "invoicing_party",
            "document_currency", "invoice_gross_amount",
            "invoice_is_cancelled", "overall_invoice_status",
            "created_by_user", "creation_date", "last_change_date_time",
        ],
    },
    {
        "id": "invoice_po_reference",
        "name": "A_SuplrInvcItemPurOrdRef",
        "label": "Invoice → PO Reference",
        "description": "Links between supplier invoice items and purchase order items. Shows which PO items each invoice line references. Fetched per group of POs via OData V2.",
        "sap_api": "A_SuplrInvcItemPurOrdRef (OData V2 / XML-Atom)",
        "tables": ["invoice_po_reference"],
        "mandatory_fields": [
            "supplier_invoice", "fiscal_year", "purchase_order",
            "purchase_order_item", "supplier_invoice_item",
        ],
        "optional_fields": [
            "referenced_amount", "referenced_quantity", "document_currency",
            "deletion_indicator", "created_by_user", "creation_date",
            "last_change_date_time",
        ],
    },
]

# Connector definitions — derived from the actual connector modules in app/connectors/
CONNECTORS = [
    {
        "id": "supplier_connector",
        "name": "Supplier Connector",
        "module": "app.connectors.supplier_connector",
        "description": "Fetches supplier master data and related sub-entities (company codes, purchasing organizations, long texts) from the SAP Business Partner API.",
        "sap_api": "A_Supplier (OData V2 / XML-Atom)",
        "protocol": "OData V2",
        "format": "XML / Atom",
        "data_fetched": "Supplier master records with company assignments, purchasing org assignments, and text notes",
        "supported_entities": ["supplier", "supplier_company", "supplier_purchasing_org", "supplier_text"],
        "capabilities": [
            "Fetches suppliers with $expand for sub-collections in a single request",
            "Falls back to per-supplier navigation calls if $expand is rejected",
            "Supports incremental sync via keyset paging on CreationDate",
            "Handles SAP quota errors gracefully (saves partial results)",
            "Resumable: continues from saved watermark on next run",
        ],
        "status": "active",
    },
    {
        "id": "purchase_order_connector",
        "name": "Purchase Order Connector",
        "module": "app.connectors.purchase_order_connector",
        "description": "Fetches purchase order headers and line items from the SAP Purchase Order API using grouped OR-filters for efficient batch retrieval.",
        "sap_api": "PurchaseOrder / PurchaseOrderItem (OData V4 / JSON)",
        "protocol": "OData V4",
        "format": "JSON",
        "data_fetched": "Purchase order headers and their line items (materials, quantities, prices, account assignments)",
        "supported_entities": ["purchase_order", "purchase_order_item"],
        "capabilities": [
            "Batch fetching with OR-filters (multiple suppliers per request)",
            "Resumable batch processing with per-supplier PO cursors",
            "Keyset paging for reliable cursor advancement",
            "PO_TOP budget per run — initial loads span multiple runs",
            "Automatic fallback if SAP rejects date filter/ordering",
        ],
        "status": "active",
    },
    {
        "id": "invoice_connector",
        "name": "Invoice Connector",
        "module": "app.connectors.invoice_connector",
        "description": "Fetches supplier invoice headers and invoice-to-PO-item references from the SAP Supplier Invoice Process API.",
        "sap_api": "A_SupplierInvoice / A_SuplrInvcItemPurOrdRef (OData V2 / XML-Atom)",
        "protocol": "OData V2",
        "format": "XML / Atom",
        "data_fetched": "Invoice headers (amounts, dates, status) and invoice-to-PO-item cross-references",
        "supported_entities": ["supplier_invoice", "invoice_po_reference"],
        "capabilities": [
            "Grouped OR-filter fetching for invoice references by PO number",
            "Grouped composite-key fetching for invoice headers",
            "Falls back to per-invoice fetching if combined filter is rejected",
            "Handles missing invoice headers gracefully (integrity step drops dangling references)",
        ],
        "status": "active",
    },
]


# ===================================================================
# 1. HEALTH & STATUS
# ===================================================================

@app.get("/api/health", tags=["Health"])
def health_check():
    """Check backend health and database connectivity."""
    db_ok = False
    db_error = None
    table_count = 0
    try:
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                db_ok = True
                # Count how many of our 8 tables exist
                cur.execute(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = ANY(%s)",
                    (TABLE_NAMES,),
                )
                table_count = cur.fetchone()[0]
    except Exception as exc:
        db_error = str(exc)

    return {
        "status": "healthy" if db_ok else "degraded",
        "backend": "online",
        "database": {
            "connected": db_ok,
            "error": db_error,
            "tables_found": table_count,
            "tables_expected": len(TABLE_NAMES),
        },
    }


# ===================================================================
# 2. CONNECTORS
# ===================================================================

@app.get("/api/connectors", tags=["Connectors"])
def list_connectors():
    """List all SAP connectors implemented in the backend."""
    return {"connectors": CONNECTORS}


@app.get("/api/connectors/{connector_id}", tags=["Connectors"])
def get_connector(connector_id: str):
    """Get detailed information about a specific connector."""
    for c in CONNECTORS:
        if c["id"] == connector_id:
            return c
    raise HTTPException(status_code=404, detail=f"Connector '{connector_id}' not found.")


# ===================================================================
# 3. DATABASE TABLES  (Extraction History section)
# ===================================================================

@app.get("/api/tables", tags=["Database Tables"])
def list_tables():
    """List all 8 database tables with their record counts."""
    tables = []
    try:
        with _db() as conn:
            with conn.cursor() as cur:
                for name in TABLE_NAMES:
                    try:
                        cur.execute(f"SELECT COUNT(*) FROM {name}")
                        count = cur.fetchone()[0]
                    except Exception:
                        conn.rollback()
                        count = None
                    tables.append({
                        "name": name,
                        "label": TABLE_LABELS.get(name, name),
                        "description": TABLE_DESCRIPTIONS.get(name, ""),
                        "record_count": count,
                    })
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}")
    return {"tables": tables}


@app.get("/api/tables/{table_name}/schema", tags=["Database Tables"])
def get_table_schema(table_name: str):
    """Get the full schema of a database table: columns, types, keys, descriptions."""
    if table_name not in TABLE_NAMES:
        raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found.")

    model_cls = TABLE_MODELS.get(table_name)
    pk_cols = TABLE_PKS.get(table_name, [])
    fk_map = TABLE_FKS.get(table_name, {})
    desc_map = FIELD_DESCRIPTIONS.get(table_name, {})

    columns = []
    try:
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name, data_type, character_maximum_length,
                           numeric_precision, numeric_scale, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = %s
                    ORDER BY ordinal_position
                    """,
                    (table_name,),
                )
                for row in cur.fetchall():
                    col_name = row[0]
                    data_type = row[1]
                    max_len = row[2]
                    num_prec = row[3]
                    num_scale = row[4]
                    nullable = row[5] == "YES"

                    # Build a display type string
                    if data_type == "character varying" and max_len:
                        display_type = f"VARCHAR({max_len})"
                    elif data_type == "numeric" and num_prec:
                        display_type = f"DECIMAL({num_prec},{num_scale or 0})"
                    elif data_type == "timestamp without time zone":
                        display_type = "TIMESTAMP"
                    elif data_type == "timestamp with time zone":
                        display_type = "TIMESTAMPTZ"
                    else:
                        display_type = data_type.upper()

                    columns.append({
                        "name": col_name,
                        "type": display_type,
                        "nullable": nullable,
                        "primary_key": col_name in pk_cols,
                        "foreign_key": fk_map.get(col_name),
                        "description": desc_map.get(col_name, ""),
                        "sap_entity": _sap_entity_for_field(table_name, col_name),
                    })
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}")

    return {
        "table": table_name,
        "label": TABLE_LABELS.get(table_name, table_name),
        "description": TABLE_DESCRIPTIONS.get(table_name, ""),
        "columns": columns,
    }


def _sap_entity_for_field(table_name: str, col_name: str) -> str:
    """Return the SAP entity/field that a column corresponds to."""
    # Map table to SAP entity name
    sap_map = {
        "supplier": "A_Supplier",
        "supplier_company": "A_Supplier / to_SupplierCompany",
        "supplier_purchasing_org": "A_Supplier / to_SupplierPurchasingOrg",
        "supplier_text": "A_Supplier / to_SupplierText",
        "purchase_order": "PurchaseOrder",
        "purchase_order_item": "PurchaseOrderItem",
        "supplier_invoice": "A_SupplierInvoice",
        "invoice_po_reference": "A_SuplrInvcItemPurOrdRef",
    }
    return sap_map.get(table_name, "")


@app.get("/api/tables/{table_name}/records", tags=["Database Tables"])
def get_table_records(
    table_name: str,
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(50, ge=1, le=500, description="Records per page"),
    search: Optional[str] = Query(None, description="Search text (searches all text columns)"),
    sort_by: Optional[str] = Query(None, description="Column to sort by"),
    sort_order: str = Query("asc", regex="^(asc|desc)$", description="Sort direction"),
):
    """Get paginated records from a database table with optional search and sorting."""
    if table_name not in TABLE_NAMES:
        raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found.")

    try:
        with _db() as conn:
            with conn.cursor() as cur:
                # Get total count
                count_sql = f"SELECT COUNT(*) FROM {table_name}"
                count_params: list = []

                # Build search clause if provided
                search_clause = ""
                if search:
                    # Get text/varchar columns for searching
                    cur.execute(
                        """
                        SELECT column_name FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = %s
                          AND data_type IN ('character varying', 'text')
                        """,
                        (table_name,),
                    )
                    text_cols = [r[0] for r in cur.fetchall()]
                    if text_cols:
                        conditions = " OR ".join(
                            f"{col}::text ILIKE %s" for col in text_cols
                        )
                        search_clause = f" WHERE ({conditions})"
                        search_param = f"%{search}%"
                        count_params = [search_param] * len(text_cols)

                cur.execute(count_sql + search_clause, count_params)
                total = cur.fetchone()[0]
                total_pages = max(1, math.ceil(total / page_size))

                # Build data query
                offset = (page - 1) * page_size
                order_clause = ""
                if sort_by:
                    # Validate sort column exists
                    cur.execute(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = %s AND column_name = %s",
                        (table_name, sort_by),
                    )
                    if cur.fetchone():
                        order_clause = f" ORDER BY {sort_by} {sort_order}"
                    else:
                        order_clause = ""
                if not order_clause:
                    # Default: order by PK columns
                    pk_cols = TABLE_PKS.get(table_name, [])
                    if pk_cols:
                        order_clause = " ORDER BY " + ", ".join(pk_cols)

                data_sql = f"SELECT * FROM {table_name}" + search_clause + order_clause + f" LIMIT %s OFFSET %s"
                data_params = count_params + [page_size, offset]
                cur.execute(data_sql, data_params)
                records = [_row_to_dict(cur, row) for row in cur.fetchall()]

                return {
                    "table": table_name,
                    "records": records,
                    "pagination": {
                        "page": page,
                        "page_size": page_size,
                        "total_records": total,
                        "total_pages": total_pages,
                    },
                }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}")


# ===================================================================
# 4. ENTITIES  (matches the existing frontend contract)
# ===================================================================

def _get_fallback_fields(entity: str) -> list[dict]:
    """Introspect dataclass models when PostgreSQL is offline or tables not yet created."""
    model_cls = TABLE_MODELS.get(entity)
    if not model_cls:
        return []
    pk_cols = TABLE_PKS.get(entity, [])
    fk_map = TABLE_FKS.get(entity, {})
    desc_map = FIELD_DESCRIPTIONS.get(entity, {})
    fields_list = []
    for f in dc_fields(model_cls):
        t_str = str(f.type)
        if "str" in t_str:
            display_type = "VARCHAR"
        elif "int" in t_str:
            display_type = "INTEGER"
        elif "Decimal" in t_str:
            display_type = "DECIMAL(15,2)"
        elif "bool" in t_str:
            display_type = "BOOLEAN"
        elif "datetime" in t_str:
            display_type = "TIMESTAMPTZ"
        elif "date" in t_str:
            display_type = "DATE"
        else:
            display_type = "TEXT"

        nullable = "Optional" in t_str or f.name not in pk_cols

        fields_list.append({
            "name": f.name,
            "type": display_type,
            "nullable": nullable,
            "primary_key": f.name in pk_cols,
            "foreign_key": fk_map.get(f.name),
            "description": desc_map.get(f.name, ""),
        })
    return fields_list


@app.get("/api/entities", tags=["Entities"])
def list_entities():
    """List database entities (tables) — compatible with existing frontend."""
    entities = []
    try:
        with _db() as conn:
            with conn.cursor() as cur:
                for name in TABLE_NAMES:
                    try:
                        cur.execute(f"SELECT COUNT(*) FROM {name}")
                        count = cur.fetchone()[0]
                    except Exception:
                        conn.rollback()
                        count = 0
                    entities.append({
                        "name": name,
                        "entity": name,
                        "label": TABLE_LABELS.get(name, name),
                        "description": TABLE_DESCRIPTIONS.get(name, ""),
                        "record_count": count,
                    })
    except Exception:
        # Graceful fallback: return entity list even if DB is offline or not yet initialized
        entities = [
            {
                "name": name,
                "entity": name,
                "label": TABLE_LABELS.get(name, name),
                "description": TABLE_DESCRIPTIONS.get(name, ""),
                "record_count": 0,
            }
            for name in TABLE_NAMES
        ]
    return {"entities": entities}


@app.get("/api/entities/{entity}/fields", tags=["Entities"])
def get_entity_fields(entity: str):
    """Get fields/columns for a database entity — compatible with existing frontend."""
    if entity not in TABLE_NAMES:
        raise HTTPException(status_code=404, detail=f"Entity '{entity}' not found.")

    pk_cols = TABLE_PKS.get(entity, [])
    fk_map = TABLE_FKS.get(entity, {})
    desc_map = FIELD_DESCRIPTIONS.get(entity, {})

    fields_list = []
    try:
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name, data_type, character_maximum_length,
                           numeric_precision, numeric_scale, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = %s
                    ORDER BY ordinal_position
                    """,
                    (entity,),
                )
                rows = cur.fetchall()
                if not rows:
                    return {"entity": entity, "fields": _get_fallback_fields(entity)}

                for row in rows:
                    col_name = row[0]
                    data_type = row[1]
                    max_len = row[2]
                    num_prec = row[3]
                    num_scale = row[4]
                    nullable = row[5] == "YES"

                    if data_type == "character varying" and max_len:
                        display_type = f"VARCHAR({max_len})"
                    elif data_type == "numeric" and num_prec:
                        display_type = f"DECIMAL({num_prec},{num_scale or 0})"
                    elif data_type == "timestamp without time zone":
                        display_type = "TIMESTAMP"
                    elif data_type == "timestamp with time zone":
                        display_type = "TIMESTAMPTZ"
                    else:
                        display_type = data_type.upper()

                    fields_list.append({
                        "name": col_name,
                        "type": display_type,
                        "nullable": nullable,
                        "primary_key": col_name in pk_cols,
                        "foreign_key": fk_map.get(col_name),
                        "description": desc_map.get(col_name, ""),
                    })
    except Exception:
        # Fall back to dataclass model introspection if DB is offline
        return {"entity": entity, "fields": _get_fallback_fields(entity)}

    return {"entity": entity, "fields": fields_list}


@app.get("/api/entities/{entity}/records", tags=["Entities"])
def get_entity_records(
    entity: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Get records from a database entity — compatible with existing frontend."""
    if entity not in TABLE_NAMES:
        raise HTTPException(status_code=404, detail=f"Entity '{entity}' not found.")

    try:
        with _db() as conn:
            with conn.cursor() as cur:
                # Check if table exists
                cur.execute(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = %s)",
                    (entity,),
                )
                if not cur.fetchone()[0]:
                    return {"entity": entity, "records": []}

                pk_cols = TABLE_PKS.get(entity, [])
                order = " ORDER BY " + ", ".join(pk_cols) if pk_cols else ""
                cur.execute(f"SELECT * FROM {entity}{order} LIMIT %s OFFSET %s", (limit, offset))
                records = [_row_to_dict(cur, row) for row in cur.fetchall()]
                return {"entity": entity, "records": records}
    except Exception:
        return {"entity": entity, "records": []}


# ===================================================================
# 5. SAP ENTITIES — for the Dashboard / Configure Extraction section
# ===================================================================

@app.get("/api/sap-entities", tags=["SAP Entities"])
def list_sap_entities():
    """List all SAP entities supported for extraction, with field metadata."""
    return {"entities": SAP_ENTITIES}


@app.get("/api/sap-entities/{entity_id}", tags=["SAP Entities"])
def get_sap_entity(entity_id: str):
    """Get details of a specific SAP entity including its mandatory/optional fields."""
    for e in SAP_ENTITIES:
        if e["id"] == entity_id:
            # Enrich with field descriptions
            table = e["tables"][0]  # primary table
            desc_map = FIELD_DESCRIPTIONS.get(table, {})
            mandatory = [
                {"name": f, "mandatory": True, "description": desc_map.get(f, "")}
                for f in e["mandatory_fields"]
            ]
            optional = [
                {"name": f, "mandatory": False, "description": desc_map.get(f, "")}
                for f in e["optional_fields"]
            ]
            return {
                **e,
                "fields": mandatory + optional,
            }
    raise HTTPException(status_code=404, detail=f"SAP entity '{entity_id}' not found.")


# ===================================================================
# 6. DATA EXTRACTION — trigger extraction from the dashboard
# ===================================================================

class ExtractionRequest(BaseModel):
    """Request body for triggering a data extraction."""
    entities: list[str]  # entity IDs to extract, e.g. ["supplier", "purchase_order"]
    selected_fields: Optional[dict[str, list[str]]] = None  # entity_id -> [field names]
    full_refresh: bool = False  # whether to ignore watermarks for this run


# Track running extractions
_extraction_tasks: dict[str, dict] = {}


@app.post("/api/extract", tags=["Extraction"])
async def trigger_extraction(req: ExtractionRequest):
    """
    Trigger a data extraction from SAP S/4HANA.

    The extraction runs the existing backend pipeline (app.main.run).
    Field selection is recorded for the frontend but does NOT alter the
    database schema — all columns are always stored; the selection controls
    what is displayed / exported to the user.
    """
    # Validate entity IDs
    valid_ids = {e["id"] for e in SAP_ENTITIES}
    invalid = [eid for eid in req.entities if eid not in valid_ids]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Unknown entities: {invalid}")

    if not req.entities:
        raise HTTPException(status_code=400, detail="No entities selected for extraction.")

    extraction_id = str(uuid.uuid4())
    _extraction_tasks[extraction_id] = {
        "id": extraction_id,
        "status": "running",
        "entities": req.entities,
        "selected_fields": req.selected_fields,
        "full_refresh": req.full_refresh,
        "started_at": datetime.utcnow().isoformat(),
        "finished_at": None,
        "error": None,
    }

    # Run extraction in background
    asyncio.get_event_loop().run_in_executor(
        None, _run_extraction, extraction_id, req.full_refresh
    )

    return {
        "extraction_id": extraction_id,
        "status": "running",
        "message": "Extraction started. Use GET /api/extract/{extraction_id} to check status.",
    }


def _run_extraction(extraction_id: str, full_refresh: bool) -> None:
    """Run the extraction pipeline in a background thread."""
    import os
    try:
        # Set env vars for this run
        if full_refresh:
            os.environ["FULL_REFRESH"] = "true"

        from app.main import run
        run()

        _extraction_tasks[extraction_id]["status"] = "completed"
        _extraction_tasks[extraction_id]["finished_at"] = datetime.utcnow().isoformat()
    except Exception as exc:
        _extraction_tasks[extraction_id]["status"] = "failed"
        _extraction_tasks[extraction_id]["error"] = f"{type(exc).__name__}: {exc}"
        _extraction_tasks[extraction_id]["finished_at"] = datetime.utcnow().isoformat()
    finally:
        if full_refresh:
            os.environ.pop("FULL_REFRESH", None)


@app.get("/api/extract/{extraction_id}", tags=["Extraction"])
def get_extraction_status(extraction_id: str):
    """Check the status of a running or completed extraction."""
    task = _extraction_tasks.get(extraction_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Extraction '{extraction_id}' not found.")
    return task


@app.get("/api/extractions", tags=["Extraction"])
def list_extractions():
    """List all extraction tasks (in-memory, current session only)."""
    return {"extractions": list(_extraction_tasks.values())}


# ===================================================================
# 7. EXTRACTION HISTORY — run_log and change_log
# ===================================================================

@app.get("/api/history/runs", tags=["History"])
def list_runs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List extraction runs from the run_log table."""
    try:
        with _db() as conn:
            with conn.cursor() as cur:
                # Check table exists
                cur.execute(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = 'run_log')"
                )
                if not cur.fetchone()[0]:
                    return {"runs": [], "total": 0, "message": "run_log table not found. Run an extraction first."}

                cur.execute("SELECT COUNT(*) FROM run_log")
                total = cur.fetchone()[0]

                cur.execute(
                    "SELECT run_id, started_at, finished_at, status, mode, "
                    "sap_calls, stats, dropped, error "
                    "FROM run_log ORDER BY started_at DESC LIMIT %s OFFSET %s",
                    (limit, offset),
                )
                runs = []
                for row in cur.fetchall():
                    runs.append({
                        "run_id": str(row[0]),
                        "started_at": row[1].isoformat() if row[1] else None,
                        "finished_at": row[2].isoformat() if row[2] else None,
                        "status": row[3],
                        "mode": row[4],
                        "sap_calls": row[5],
                        "stats": row[6] if isinstance(row[6], dict) else {},
                        "dropped": row[7] if isinstance(row[7], dict) else {},
                        "error": row[8],
                    })
                return {"runs": runs, "total": total}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}")


@app.get("/api/history/runs/{run_id}", tags=["History"])
def get_run_detail(run_id: str):
    """Get detailed information about a specific extraction run."""
    try:
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT run_id, started_at, finished_at, status, mode, "
                    "sap_calls, stats, dropped, error "
                    "FROM run_log WHERE run_id = %s",
                    (run_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")

                # Get change count for this run
                cur.execute(
                    "SELECT COUNT(*) FROM change_log WHERE run_id = %s",
                    (run_id,),
                )
                change_count = cur.fetchone()[0]

                return {
                    "run_id": str(row[0]),
                    "started_at": row[1].isoformat() if row[1] else None,
                    "finished_at": row[2].isoformat() if row[2] else None,
                    "status": row[3],
                    "mode": row[4],
                    "sap_calls": row[5],
                    "stats": row[6] if isinstance(row[6], dict) else {},
                    "dropped": row[7] if isinstance(row[7], dict) else {},
                    "error": row[8],
                    "changes_logged": change_count,
                }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}")


@app.get("/api/history/changes", tags=["History"])
def list_changes(
    run_id: Optional[str] = Query(None, description="Filter by run ID"),
    table_name: Optional[str] = Query(None, description="Filter by table name"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List change log entries with optional filtering."""
    try:
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = 'change_log')"
                )
                if not cur.fetchone()[0]:
                    return {"changes": [], "total": 0}

                where_parts: list[str] = []
                params: list = []
                if run_id:
                    where_parts.append("run_id = %s")
                    params.append(run_id)
                if table_name:
                    where_parts.append("table_name = %s")
                    params.append(table_name)

                where = " WHERE " + " AND ".join(where_parts) if where_parts else ""

                cur.execute(f"SELECT COUNT(*) FROM change_log{where}", params)
                total = cur.fetchone()[0]

                cur.execute(
                    f"SELECT id, run_id, table_name, record_key, change_type, "
                    f"changed_fields, changed_at FROM change_log{where} "
                    f"ORDER BY changed_at DESC LIMIT %s OFFSET %s",
                    params + [limit, offset],
                )
                changes = []
                for row in cur.fetchall():
                    changes.append({
                        "id": row[0],
                        "run_id": str(row[1]) if row[1] else None,
                        "table_name": row[2],
                        "record_key": row[3],
                        "change_type": row[4],
                        "changed_fields": row[5],
                        "changed_at": row[6].isoformat() if row[6] else None,
                    })
                return {"changes": changes, "total": total}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}")


# ===================================================================
# 8. SYNC STATE — current watermarks and cursors
# ===================================================================

@app.get("/api/sync-state", tags=["Sync State"])
def get_sync_state():
    """Get the current sync state: watermarks and PO cursors."""
    try:
        with _db() as conn:
            with conn.cursor() as cur:
                # Watermarks
                watermarks = []
                try:
                    cur.execute(
                        "SELECT entity, watermark_field, last_value, last_key, last_run_id, updated_at "
                        "FROM sync_state ORDER BY entity"
                    )
                    for row in cur.fetchall():
                        watermarks.append({
                            "entity": row[0],
                            "watermark_field": row[1],
                            "last_value": row[2].isoformat() if row[2] else None,
                            "last_key": row[3],
                            "last_run_id": str(row[4]) if row[4] else None,
                            "updated_at": row[5].isoformat() if row[5] else None,
                        })
                except Exception:
                    conn.rollback()

                # PO cursor summary
                po_cursor_stats = {}
                try:
                    cur.execute("SELECT COUNT(*) FROM supplier_po_cursor")
                    po_cursor_stats["total_suppliers"] = cur.fetchone()[0]
                    cur.execute("SELECT COUNT(*) FROM supplier")
                    po_cursor_stats["total_suppliers_in_db"] = cur.fetchone()[0]
                    cur.execute("SELECT MIN(last_value), MAX(last_value) FROM supplier_po_cursor")
                    row = cur.fetchone()
                    po_cursor_stats["oldest_cursor"] = row[0].isoformat() if row[0] else None
                    po_cursor_stats["newest_cursor"] = row[1].isoformat() if row[1] else None
                except Exception:
                    conn.rollback()

                return {
                    "watermarks": watermarks,
                    "po_cursor_summary": po_cursor_stats,
                }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}")


# ===================================================================
# 9. DASHBOARD STATS — summary data for the dashboard home
# ===================================================================

@app.get("/api/dashboard/stats", tags=["Dashboard"])
def dashboard_stats():
    """Get summary statistics for the dashboard overview."""
    stats = {
        "tables": {},
        "total_records": 0,
        "last_run": None,
        "connectors": len(CONNECTORS),
        "sap_entities": len(SAP_ENTITIES),
    }

    try:
        with _db() as conn:
            with conn.cursor() as cur:
                for name in TABLE_NAMES:
                    try:
                        cur.execute(f"SELECT COUNT(*) FROM {name}")
                        count = cur.fetchone()[0]
                        stats["tables"][name] = count
                        stats["total_records"] += count
                    except Exception:
                        conn.rollback()
                        stats["tables"][name] = 0

                # Last run info
                try:
                    cur.execute(
                        "SELECT run_id, started_at, finished_at, status, mode, sap_calls "
                        "FROM run_log ORDER BY started_at DESC LIMIT 1"
                    )
                    row = cur.fetchone()
                    if row:
                        stats["last_run"] = {
                            "run_id": str(row[0]),
                            "started_at": row[1].isoformat() if row[1] else None,
                            "finished_at": row[2].isoformat() if row[2] else None,
                            "status": row[3],
                            "mode": row[4],
                            "sap_calls": row[5],
                        }
                except Exception:
                    conn.rollback()

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}")

    return stats
