"""
Field-mapping functions — convert SAP API response dicts into
the Python model dataclasses defined in app.models.

Each mapper handles:
  • SAP field-name → PostgreSQL column-name translation
  • Simple type conversions (dates, booleans, decimals)
  • Preserving leading zeros in string identifiers
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

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
# Conversion helpers
# ------------------------------------------------------------------

def _str(value: Any) -> Optional[str]:
    """Return a stripped string or None if empty / null."""
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _bool(value: Any) -> Optional[bool]:
    """Convert SAP boolean representations to Python bool."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in ("true", "1", "x"):
        return True
    if s in ("false", "0", ""):
        return False
    return None


def _date(value: Any) -> Optional[date]:
    """Parse dates from SAP formats: '2016-08-04' or '2016-08-04T00:00:00'."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        # Try ISO date first
        return date.fromisoformat(s[:10])
    except (ValueError, IndexError):
        return None


def _timestamp(value: Any) -> Optional[datetime]:
    """Parse timestamps from SAP ISO-8601 strings."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        # Handle 'Z' suffix
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _decimal(value: Any) -> Optional[Decimal]:
    """Convert numeric string / number to Decimal."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


# ------------------------------------------------------------------
# Supplier mappers  (OData V2 – properties come as a dict of
#                     extracted XML <d:FieldName> elements)
# ------------------------------------------------------------------

def map_supplier(props: dict) -> Supplier:
    return Supplier(
        supplier=props["Supplier"],
        supplier_name=_str(props.get("SupplierName")),
        supplier_full_name=_str(props.get("SupplierFullName")),
        supplier_account_group=_str(props.get("SupplierAccountGroup")),
        alternative_payee_account_number=_str(props.get("AlternativePayeeAccountNumber")),
        authorization_group=_str(props.get("AuthorizationGroup")),
        business_partner_pan_number=_str(props.get("BusinessPartnerPanNumber")),
        customer=_str(props.get("Customer")),
        payment_is_blocked_for_supplier=_bool(props.get("PaymentIsBlockedForSupplier")),
        posting_is_blocked=_bool(props.get("PostingIsBlocked")),
        purchasing_is_blocked=_bool(props.get("PurchasingIsBlocked")),
        vat_registration=_str(props.get("VATRegistration")),
        deletion_indicator=_bool(props.get("DeletionIndicator")),
        created_by_user=_str(props.get("CreatedByUser")),
        creation_date=_date(props.get("CreationDate")),
        last_change_date_time=_timestamp(props.get("LastChangeDateTime")),
    )


def map_supplier_company(supplier_id: str, props: dict) -> SupplierCompany:
    return SupplierCompany(
        supplier=supplier_id,
        company_code=props.get("CompanyCode", ""),
        company_name=_str(props.get("CompanyName")),
        company_address=_str(props.get("CompanyAddress")),
        deletion_indicator=_bool(props.get("DeletionIndicator")),
        created_by_user=_str(props.get("CreatedByUser")),
        creation_date=_date(props.get("CreationDate")),
        last_change_date_time=_timestamp(props.get("LastChangeDateTime")),
    )


def map_supplier_purchasing_org(supplier_id: str, props: dict) -> SupplierPurchasingOrg:
    return SupplierPurchasingOrg(
        supplier=supplier_id,
        purchasing_organization=props.get("PurchasingOrganization", ""),
        purchasing_org_name=_str(props.get("PurchasingOrgName")),
        deletion_indicator=_bool(props.get("DeletionIndicator")),
        created_by_user=_str(props.get("CreatedByUser")),
        creation_date=_date(props.get("CreationDate")),
        last_change_date_time=_timestamp(props.get("LastChangeDateTime")),
    )


def map_supplier_text(supplier_id: str, props: dict) -> SupplierText:
    return SupplierText(
        supplier=supplier_id,
        language=props.get("Language", ""),
        text_type=props.get("TextType", ""),
        text=_str(props.get("LongText") or props.get("Text")),
        deletion_indicator=_bool(props.get("DeletionIndicator")),
        created_by_user=_str(props.get("CreatedByUser")),
        creation_date=_date(props.get("CreationDate")),
        last_change_date_time=_timestamp(props.get("LastChangeDateTime")),
    )


# ------------------------------------------------------------------
# Purchase order mappers  (OData V4 – JSON dict)
# ------------------------------------------------------------------

def map_purchase_order(props: dict) -> PurchaseOrder:
    return PurchaseOrder(
        purchase_order=props["PurchaseOrder"],
        supplier=_str(props.get("Supplier")),
        purchase_order_type=_str(props.get("PurchaseOrderType")),
        purchase_order_subtype=_str(props.get("PurchaseOrderSubtype")),
        purchasing_document_origin=_str(props.get("PurchasingDocumentOrigin")),
        purchasing_document_process_code=_str(props.get("PurchasingDocumentProcessCode")),
        created_by_user=_str(props.get("CreatedByUser")),
        creation_date=_date(props.get("CreationDate")),
        purchase_order_date=_date(props.get("PurchaseOrderDate")),
        last_change_date_time=_timestamp(props.get("LastChangeDateTime")),
        validity_start_date=_date(props.get("ValidityStartDate")),
        validity_end_date=_date(props.get("ValidityEndDate")),
        msg_on_goods_receipt_is_required=_bool(props.get("MsgOnGoodsReceiptIsRequested")),
        company_code=_str(props.get("CompanyCode")),
        purchasing_organization=_str(props.get("PurchasingOrganization")),
        document_currency=_str(props.get("DocumentCurrency")),
        deletion_indicator=_bool(props.get("PurchaseOrderDeletionCode")),
        purchase_order_is_blocked=_bool(props.get("PurchaseOrderIsBlocked")),
        invoices_is_blocked=_bool(props.get("InvoicesIsBlocked")),
        goods_receipt_is_blocked=_bool(props.get("GoodsReceiptIsBlocked")),
        overall_release_status=_str(props.get("OverallReleaseStatus")),
    )


def map_purchase_order_item(props: dict) -> PurchaseOrderItem:
    return PurchaseOrderItem(
        purchase_order=props["PurchaseOrder"],
        purchase_order_item=props["PurchaseOrderItem"],
        material=_str(props.get("Material")),
        short_text=_str(props.get("PurchaseOrderItemText") or props.get("ShortText")),
        order_quantity=_decimal(props.get("OrderQuantity")),
        order_unit=_str(
            props.get("PurchaseOrderQuantityUnit")
            or props.get("OrderQuantityUnit")
            or props.get("OrderUnit")
        ),
        net_price_amount=_decimal(props.get("NetPriceAmount")),
        net_price_unit=_str(
            props.get("NetPriceQuantityUnit")
            or props.get("NetPriceUnit")
        ),
        item_category=_str(
            props.get("PurchasingDocumentItemCategory")
            or props.get("ItemCategory")
        ),
        deletion_indicator=_bool(props.get("PurchaseOrderItemDeletionCode") or props.get("DeletionIndicator")),
        goods_receipt_is_expected=_bool(props.get("GoodsReceiptIsExpected")),
        invoices_expected=_bool(props.get("InvoiceIsExpected") or props.get("InvoicesExpected")),
        plant=_str(props.get("Plant")),
        storage_location=_str(props.get("StorageLocation")),
        account_assignment_category=_str(props.get("AccountAssignmentCategory")),
        cost_center=_str(props.get("CostCenter")),
        wbs_account=_str(props.get("WBSElement") or props.get("WBS_Account")),
        material_group=_str(props.get("MaterialGroup")),
        created_by_user=_str(props.get("CreatedByUser")),
        creation_date=_date(props.get("CreationDate")),
        last_change_date_time=_timestamp(props.get("LastChangeDateTime")),
    )


# ------------------------------------------------------------------
# Invoice mappers  (OData V2 – XML properties dict)
# ------------------------------------------------------------------

def map_supplier_invoice(props: dict) -> SupplierInvoice:
    return SupplierInvoice(
        supplier_invoice=props["SupplierInvoice"],
        fiscal_year=props["FiscalYear"],
        supplier=_str(props.get("InvoicingParty") or props.get("Supplier")),
        purchase_order=_str(props.get("PurchaseOrder")),
        company_code=_str(props.get("CompanyCode")),
        document_date=_date(props.get("DocumentDate")),
        posting_date=_date(props.get("PostingDate")),
        invoicing_party=_str(props.get("InvoicingParty")),
        document_currency=_str(props.get("DocumentCurrency")),
        invoice_gross_amount=_decimal(props.get("InvoiceGrossAmount")),
        invoice_is_cancelled=_bool(props.get("InvoiceIsCancelled") or props.get("IsInvoiceCancelled")),
        overall_invoice_status=_str(props.get("OverallInvoiceStatus") or props.get("SupplierInvoiceStatus")),
        created_by_user=_str(props.get("CreatedByUser")),
        creation_date=_date(props.get("CreationDate")),
        last_change_date_time=_timestamp(props.get("LastChangeDateTime")),
    )


def map_invoice_po_reference(props: dict) -> InvoicePOReference:
    return InvoicePOReference(
        supplier_invoice=props["SupplierInvoice"],
        fiscal_year=props["FiscalYear"],
        purchase_order=props["PurchaseOrder"],
        purchase_order_item=props["PurchaseOrderItem"],
        supplier_invoice_item=props["SupplierInvoiceItem"],
        referenced_amount=_decimal(props.get("SupplierInvoiceItemAmount")),
        referenced_quantity=_decimal(props.get("QuantityInPurchaseOrderUnit")),
        document_currency=_str(props.get("DocumentCurrency")),
        deletion_indicator=_bool(props.get("DeletionIndicator")),
        created_by_user=_str(props.get("CreatedByUser")),
        creation_date=_date(props.get("CreationDate")),
        last_change_date_time=_timestamp(props.get("LastChangeDateTime")),
    )
