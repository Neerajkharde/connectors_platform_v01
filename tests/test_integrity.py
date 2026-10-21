"""Tests for the referential-integrity step (prevents FK violations)."""

import unittest

from app.integrity import enforce_integrity
from app.models import (InvoicePOReference, PurchaseOrder, PurchaseOrderItem, Supplier,
                        SupplierCompany, SupplierInvoice, SupplierText)


def run(**kw):
    args = dict(suppliers=[], companies=[], purch_orgs=[], texts=[], orders=[], items=[],
                invoices=[], po_refs=[])
    args.update(kw)
    return enforce_integrity(**args)


class TestIntegrity(unittest.TestCase):
    def setUp(self):
        self.sup = Supplier("S1")
        self.po = PurchaseOrder("P1", supplier="S1")
        self.item = PurchaseOrderItem("P1", "10")

    def test_consistent_data_is_untouched(self):
        inv = SupplierInvoice("I1", "2026", supplier="S1", purchase_order="P1")
        ref = InvoicePOReference("I1", "2026", "P1", "10", "1")
        clean, report = run(suppliers=[self.sup], orders=[self.po], items=[self.item],
                            invoices=[inv], po_refs=[ref])
        self.assertEqual(report, {})
        self.assertEqual(clean["po_refs"], [ref])

    def test_reference_without_invoice_header_is_dropped(self):
        ref = InvoicePOReference("MISSING", "2026", "P1", "10", "1")
        clean, report = run(suppliers=[self.sup], orders=[self.po], items=[self.item], po_refs=[ref])
        self.assertEqual(clean["po_refs"], [])
        self.assertEqual(report["invoice_po_reference: invoice header missing (dropped)"], 1)

    def test_reference_to_unknown_po_item_is_dropped(self):
        inv = SupplierInvoice("I1", "2026")
        ref = InvoicePOReference("I1", "2026", "P1", "99", "1")
        clean, _ = run(suppliers=[self.sup], orders=[self.po], items=[self.item], invoices=[inv], po_refs=[ref])
        self.assertEqual(clean["po_refs"], [])

    def test_unknown_invoicing_party_keeps_invoice_but_nulls_fk(self):
        inv = SupplierInvoice("I1", "2026", supplier="GHOST", invoicing_party="GHOST")
        clean, report = run(suppliers=[self.sup], invoices=[inv])
        self.assertEqual(len(clean["invoices"]), 1)
        self.assertIsNone(clean["invoices"][0].supplier)
        self.assertEqual(clean["invoices"][0].invoicing_party, "GHOST")  # information preserved
        self.assertEqual(len(report), 1)

    def test_invoice_po_is_derived_from_references(self):
        inv = SupplierInvoice("I1", "2026", supplier="S1")  # header has no PO
        ref = InvoicePOReference("I1", "2026", "P1", "10", "1")
        clean, _ = run(suppliers=[self.sup], orders=[self.po], items=[self.item], invoices=[inv], po_refs=[ref])
        self.assertEqual(clean["invoices"][0].purchase_order, "P1")

    def test_invoice_pointing_to_unfetched_po_gets_null(self):
        inv = SupplierInvoice("I1", "2026", purchase_order="NOPE")
        clean, _ = run(suppliers=[self.sup], invoices=[inv])
        self.assertIsNone(clean["invoices"][0].purchase_order)

    def test_children_of_unknown_supplier_and_empty_keys_dropped(self):
        comp_ok = SupplierCompany("S1", "1710")
        comp_orphan = SupplierCompany("GHOST", "1710")
        text_empty_key = SupplierText("S1", "EN", "")
        clean, report = run(suppliers=[self.sup], companies=[comp_ok, comp_orphan], texts=[text_empty_key])
        self.assertEqual(clean["companies"], [comp_ok])
        self.assertEqual(clean["texts"], [])
        self.assertEqual(sum(report.values()), 2)

    def test_items_of_unknown_po_dropped(self):
        clean, _ = run(suppliers=[self.sup], orders=[self.po], items=[self.item, PurchaseOrderItem("P404", "10")])
        self.assertEqual(clean["items"], [self.item])


if __name__ == "__main__":
    unittest.main()
