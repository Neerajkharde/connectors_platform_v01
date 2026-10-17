"""
Python data models (plain dataclasses) for all eight ERD tables.
Field types mirror the PostgreSQL schema so converters can populate
instances directly.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Optional


# ------------------------------------------------------------------
# 1. SUPPLIER
# ------------------------------------------------------------------
@dataclass
class Supplier:
    supplier: str
    supplier_name: Optional[str] = None
    supplier_full_name: Optional[str] = None
    supplier_account_group: Optional[str] = None
    alternative_payee_account_number: Optional[str] = None
    authorization_group: Optional[str] = None
    business_partner_pan_number: Optional[str] = None
    customer: Optional[str] = None
    payment_is_blocked_for_supplier: Optional[bool] = None
    posting_is_blocked: Optional[bool] = None
    purchasing_is_blocked: Optional[bool] = None
    vat_registration: Optional[str] = None
    deletion_indicator: Optional[bool] = None
    created_by_user: Optional[str] = None
    creation_date: Optional[date] = None
    last_change_date_time: Optional[datetime] = None


# ------------------------------------------------------------------
# 2. SUPPLIER_COMPANY
# ------------------------------------------------------------------
@dataclass
class SupplierCompany:
    supplier: str
    company_code: str
    company_name: Optional[str] = None
    company_address: Optional[str] = None
    deletion_indicator: Optional[bool] = None
    created_by_user: Optional[str] = None
    creation_date: Optional[date] = None
    last_change_date_time: Optional[datetime] = None


# ------------------------------------------------------------------
# 3. SUPPLIER_PURCHASING_ORG
# ------------------------------------------------------------------
@dataclass
class SupplierPurchasingOrg:
    supplier: str
    purchasing_organization: str
    purchasing_org_name: Optional[str] = None
    deletion_indicator: Optional[bool] = None
    created_by_user: Optional[str] = None
    creation_date: Optional[date] = None
    last_change_date_time: Optional[datetime] = None


# ------------------------------------------------------------------
# 4. SUPPLIER_TEXT
# ------------------------------------------------------------------
@dataclass
class SupplierText:
    supplier: str
    language: str
    text_type: str
    text: Optional[str] = None
    deletion_indicator: Optional[bool] = None
    created_by_user: Optional[str] = None
    creation_date: Optional[date] = None
    last_change_date_time: Optional[datetime] = None


# ------------------------------------------------------------------
# 5. PURCHASE_ORDER
# ------------------------------------------------------------------
@dataclass
class PurchaseOrder:
    purchase_order: str
    supplier: Optional[str] = None
    purchase_order_type: Optional[str] = None
    purchase_order_subtype: Optional[str] = None
    purchasing_document_origin: Optional[str] = None
    purchasing_document_process_code: Optional[str] = None
    created_by_user: Optional[str] = None
    creation_date: Optional[date] = None
    purchase_order_date: Optional[date] = None
    last_change_date_time: Optional[datetime] = None
    validity_start_date: Optional[date] = None
    validity_end_date: Optional[date] = None
    msg_on_goods_receipt_is_required: Optional[bool] = None
    company_code: Optional[str] = None
    purchasing_organization: Optional[str] = None
    document_currency: Optional[str] = None
    deletion_indicator: Optional[bool] = None
    purchase_order_is_blocked: Optional[bool] = None
    invoices_is_blocked: Optional[bool] = None
    goods_receipt_is_blocked: Optional[bool] = None
    overall_release_status: Optional[str] = None


# ------------------------------------------------------------------
# 6. PURCHASE_ORDER_ITEM
# ------------------------------------------------------------------
@dataclass
class PurchaseOrderItem:
    purchase_order: str
    purchase_order_item: str
    material: Optional[str] = None
    short_text: Optional[str] = None
    order_quantity: Optional[Decimal] = None
    order_unit: Optional[str] = None
    net_price_amount: Optional[Decimal] = None
    net_price_unit: Optional[str] = None
    item_category: Optional[str] = None
    deletion_indicator: Optional[bool] = None
    goods_receipt_is_expected: Optional[bool] = None
    invoices_expected: Optional[bool] = None
    plant: Optional[str] = None
    storage_location: Optional[str] = None
    account_assignment_category: Optional[str] = None
    cost_center: Optional[str] = None
    wbs_account: Optional[str] = None
    material_group: Optional[str] = None
    created_by_user: Optional[str] = None
    creation_date: Optional[date] = None
    last_change_date_time: Optional[datetime] = None


# ------------------------------------------------------------------
# 7. SUPPLIER_INVOICE
# ------------------------------------------------------------------
@dataclass
class SupplierInvoice:
    supplier_invoice: str
    fiscal_year: str
    supplier: Optional[str] = None
    purchase_order: Optional[str] = None
    company_code: Optional[str] = None
    document_date: Optional[date] = None
    posting_date: Optional[date] = None
    invoicing_party: Optional[str] = None
    document_currency: Optional[str] = None
    invoice_gross_amount: Optional[Decimal] = None
    invoice_is_cancelled: Optional[bool] = None
    overall_invoice_status: Optional[str] = None
    created_by_user: Optional[str] = None
    creation_date: Optional[date] = None
    last_change_date_time: Optional[datetime] = None


# ------------------------------------------------------------------
# 8. INVOICE_PO_REFERENCE
# ------------------------------------------------------------------
@dataclass
class InvoicePOReference:
    supplier_invoice: str
    fiscal_year: str
    purchase_order: str
    purchase_order_item: str
    supplier_invoice_item: str
    referenced_amount: Optional[Decimal] = None
    referenced_quantity: Optional[Decimal] = None
    document_currency: Optional[str] = None
    deletion_indicator: Optional[bool] = None
    created_by_user: Optional[str] = None
    creation_date: Optional[date] = None
    last_change_date_time: Optional[datetime] = None
