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


class TestFixedMappings(unittest.TestCase):
    """Regression tests for bugs found in review of the original mappers."""

    def test_supplier_text_uses_longtextid_as_key(self):
        # SAP's real key field is LongTextID; the old mapper read 'TextType' and stored ''
        # for every row, so a supplier's 2nd text silently collided with the 1st.
        a = map_supplier_text("1018", {"Language": "EN", "LongTextID": "0001", "LongText": "a"})
        b = map_supplier_text("1018", {"Language": "EN", "LongTextID": "0002", "LongText": "b"})
        self.assertEqual((a.text_type, b.text_type), ("0001", "0002"))

    def test_timestamp_with_7_fraction_digits_and_tz(self):
        self.assertEqual(_timestamp("2026-09-26T13:19:33.1234567Z"), datetime(2026, 9, 26, 13, 19, 33, 123456))
        self.assertEqual(_timestamp("2026-09-26T15:19:33+02:00"), datetime(2026, 9, 26, 13, 19, 33))
        self.assertIsNone(_timestamp("not a date"))

    def test_deletion_codes(self):
        base = {"PurchaseOrder": "1"}
        self.assertIs(map_purchase_order({**base, "PurchaseOrderDeletionCode": "L"}).deletion_indicator, True)
        self.assertIs(map_purchase_order({**base, "PurchaseOrderDeletionCode": ""}).deletion_indicator, False)
        self.assertIsNone(map_purchase_order(base).deletion_indicator)
        item = {"PurchaseOrder": "1", "PurchaseOrderItem": "10"}
        self.assertIs(map_purchase_order_item({**item, "PurchaseOrderItemDeletionCode": "L"}).deletion_indicator, True)

    def test_item_numbers_are_normalised_so_foreign_keys_match(self):
        item = map_purchase_order_item({"PurchaseOrder": "1", "PurchaseOrderItem": "00010"})
        ref = map_invoice_po_reference({"SupplierInvoice": "5", "FiscalYear": "2026", "PurchaseOrder": "1",
                                        "PurchaseOrderItem": "10", "SupplierInvoiceItem": "000001"})
        self.assertEqual(item.purchase_order_item, ref.purchase_order_item)
        self.assertEqual(ref.supplier_invoice_item, "1")

    def test_invoice_cancelled_from_reverse_document(self):
        base = {"SupplierInvoice": "5", "FiscalYear": "2026"}
        self.assertIs(map_supplier_invoice({**base, "ReverseDocument": "5100000099"}).invoice_is_cancelled, True)
        self.assertIs(map_supplier_invoice({**base, "ReverseDocument": ""}).invoice_is_cancelled, False)
        self.assertIsNone(map_supplier_invoice(base).invoice_is_cancelled)

    def test_false_values_are_not_lost_by_or_fallbacks(self):
        # old code: _bool(a or b) skipped a legitimate False
        po = map_supplier_invoice({"SupplierInvoice": "5", "FiscalYear": "2026", "InvoiceIsCancelled": False,
                                   "ReverseDocument": "X"})
        self.assertIs(po.invoice_is_cancelled, False)


if __name__ == "__main__":
    unittest.main()
