"""
Unit tests for the field-mapping functions.
Verifies that SAP API response dicts are correctly converted to
Python model dataclasses with proper type conversions.
"""

import unittest
from datetime import date, datetime
from decimal import Decimal

from app.mapping.mappers import (
    map_supplier,
    map_supplier_company,
    map_supplier_purchasing_org,
    map_supplier_text,
    map_purchase_order,
    map_purchase_order_item,
    map_supplier_invoice,
    map_invoice_po_reference,
    _bool,
    _date,
    _timestamp,
    _decimal,
    _str,
)


class TestConversionHelpers(unittest.TestCase):
    """Test the low-level type converters."""

    def test_str_returns_none_for_empty(self):
        self.assertIsNone(_str(""))
        self.assertIsNone(_str("   "))
        self.assertIsNone(_str(None))

    def test_str_strips_whitespace(self):
        self.assertEqual(_str("  hello  "), "hello")

    def test_bool_true_values(self):
        self.assertTrue(_bool("true"))
        self.assertTrue(_bool("1"))
        self.assertTrue(_bool(True))
        self.assertTrue(_bool("X"))

    def test_bool_false_values(self):
        self.assertFalse(_bool("false"))
        self.assertFalse(_bool("0"))
        self.assertFalse(_bool(False))

    def test_bool_none(self):
        self.assertIsNone(_bool(None))

    def test_date_iso(self):
        self.assertEqual(_date("2016-08-04"), date(2016, 8, 4))

    def test_date_with_time(self):
        self.assertEqual(_date("2018-10-29T00:00:00"), date(2018, 10, 29))

    def test_date_none(self):
        self.assertIsNone(_date(None))
        self.assertIsNone(_date(""))

    def test_timestamp_iso(self):
        ts = _timestamp("2026-09-26T13:19:33Z")
        self.assertIsInstance(ts, datetime)
        self.assertEqual(ts.year, 2026)
        self.assertEqual(ts.month, 9)

    def test_decimal(self):
        self.assertEqual(_decimal("600.00"), Decimal("600.00"))
        self.assertEqual(_decimal(0), Decimal("0"))
        self.assertIsNone(_decimal(None))


class TestSupplierMapper(unittest.TestCase):
    """Test mapping a raw SAP supplier response to the Supplier model."""

    SAMPLE = {
        "Supplier": "1018",
        "SupplierName": "Bechtle AG Kriek street",
        "SupplierFullName": "Company Bechtle AGKriek street/74172 Neckarsulm",
        "SupplierAccountGroup": "SUPL",
        "AlternativePayeeAccountNumber": "",
        "AuthorizationGroup": "",
        "BusinessPartnerPanNumber": "",
        "Customer": "",
        "PaymentIsBlockedForSupplier": "false",
        "PostingIsBlocked": "false",
        "PurchasingIsBlocked": "false",
        "VATRegistration": "",
        "DeletionIndicator": "false",
        "CreatedByUser": "CB9980000295",
        "CreationDate": "2018-10-29T00:00:00",
        "LastChangeDateTime": None,
    }

    def test_maps_key_fields(self):
        s = map_supplier(self.SAMPLE)
        self.assertEqual(s.supplier, "1018")
        self.assertEqual(s.supplier_name, "Bechtle AG Kriek street")
        self.assertEqual(s.supplier_account_group, "SUPL")

    def test_maps_booleans(self):
        s = map_supplier(self.SAMPLE)
        self.assertFalse(s.payment_is_blocked_for_supplier)
        self.assertFalse(s.deletion_indicator)

    def test_maps_date(self):
        s = map_supplier(self.SAMPLE)
        self.assertEqual(s.creation_date, date(2018, 10, 29))

    def test_empty_strings_become_none(self):
        s = map_supplier(self.SAMPLE)
        self.assertIsNone(s.authorization_group)
        self.assertIsNone(s.customer)


class TestPurchaseOrderMapper(unittest.TestCase):
    """Test mapping a raw SAP PO JSON response."""

    SAMPLE = {
        "PurchaseOrder": "4500000001",
        "PurchaseOrderType": "NB",
        "PurchaseOrderSubtype": "",
        "PurchasingDocumentOrigin": "9",
        "PurchasingDocumentProcessCode": "",
        "CreatedByUser": "CB9980000026",
        "CreationDate": "2016-08-04",
        "PurchaseOrderDate": "2016-08-04",
        "LastChangeDateTime": None,
        "ValidityStartDate": None,
        "ValidityEndDate": None,
        "MsgOnGoodsReceiptIsRequested": False,
        "CompanyCode": "1710",
        "PurchasingOrganization": "1710",
        "DocumentCurrency": "USD",
        "Supplier": "17300001",
        "PurchaseOrderDeletionCode": "",
    }

    def test_maps_fields(self):
        po = map_purchase_order(self.SAMPLE)
        self.assertEqual(po.purchase_order, "4500000001")
        self.assertEqual(po.supplier, "17300001")
        self.assertEqual(po.company_code, "1710")
        self.assertEqual(po.document_currency, "USD")
        self.assertEqual(po.creation_date, date(2016, 8, 4))


class TestInvoicePORefMapper(unittest.TestCase):
    """Test mapping a raw SAP invoice-PO reference response."""

    SAMPLE = {
        "SupplierInvoice": "5100000004",
        "FiscalYear": "2016",
        "SupplierInvoiceItem": "1",
        "PurchaseOrder": "4500000013",
        "PurchaseOrderItem": "10",
        "DocumentCurrency": "USD",
        "SupplierInvoiceItemAmount": "600.00",
        "QuantityInPurchaseOrderUnit": "20",
    }

    def test_maps_composite_key(self):
        ref = map_invoice_po_reference(self.SAMPLE)
        self.assertEqual(ref.supplier_invoice, "5100000004")
        self.assertEqual(ref.fiscal_year, "2016")
        self.assertEqual(ref.purchase_order, "4500000013")
        self.assertEqual(ref.purchase_order_item, "10")
        self.assertEqual(ref.supplier_invoice_item, "1")

    def test_maps_amounts(self):
        ref = map_invoice_po_reference(self.SAMPLE)
        self.assertEqual(ref.referenced_amount, Decimal("600.00"))
        self.assertEqual(ref.referenced_quantity, Decimal("20"))
        self.assertEqual(ref.document_currency, "USD")


if __name__ == "__main__":
    unittest.main()
