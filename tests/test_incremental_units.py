"""Unit tests for the incremental pieces that need no database."""

import unittest
from datetime import datetime

import requests

from app.connectors import purchase_order_connector, supplier_connector
from app.integrity import enforce_integrity
from app.models import InvoicePOReference, PurchaseOrder, PurchaseOrderItem, Supplier
from app.odata import and_filter, or_filter, watermark_filter
from app.sap_client import SAPQuotaExceeded
from app.sync_state import max_field_value
from tests.test_connectors import RecordingClient, http_error
from tests.test_odata import HEAD, entry

WM = datetime(2026, 10, 24, 7, 30, 5)


class TestWatermarkFilter(unittest.TestCase):
    def test_v2_literals(self):
        self.assertEqual(watermark_filter("F", "date", WM, 2), "F ge datetime'2026-10-24T00:00:00'")
        self.assertEqual(watermark_filter("F", "datetime", WM, 2), "F ge datetime'2026-10-24T07:30:05'")
        self.assertEqual(watermark_filter("F", "datetimeoffset", WM, 2),
                         "F ge datetimeoffset'2026-10-24T07:30:05Z'")

    def test_v4_literals_are_bare(self):
        self.assertEqual(watermark_filter("F", "date", WM, 4), "F ge 2026-10-24")
        self.assertEqual(watermark_filter("F", "datetimeoffset", WM, 4), "F ge 2026-10-24T07:30:05Z")

    def test_and_filter_groups_the_or_part(self):
        f = and_filter(or_filter("Supplier", ["a", "b"]), "D ge 1")
        self.assertEqual(f, "(Supplier eq 'a' or Supplier eq 'b') and (D ge 1)")
        self.assertEqual(and_filter(None, "x"), "x")

    def test_max_field_value(self):
        rows = [{"D": "2026-01-01T10:00:00Z"}, {"D": "2026-03-01T10:00:00Z"}, {"D": None}, {}]
        self.assertEqual(max_field_value(rows, "D"), datetime(2026, 3, 1, 10))
        self.assertIsNone(max_field_value([{}], "D"))


class TestSupplierConnectorIncremental(unittest.TestCase):
    def test_watermark_adds_filter_and_stable_order(self):
        c = RecordingClient(lambda p, q: HEAD + "</feed>")
        data = supplier_connector.fetch_all_suppliers_with_related(
            c, top=10, page_size=10, watermark=WM, date_field="LastChangeDateTime",
            date_type="datetimeoffset")
        params = c.calls[0][1]
        self.assertEqual(params["$filter"], "LastChangeDateTime ge datetimeoffset'2026-10-24T07:30:05Z'")
        self.assertEqual(params["$orderby"], "LastChangeDateTime asc, Supplier asc")
        self.assertTrue(data["_ordered"])

    def test_first_run_is_ordered_but_unfiltered(self):
        c = RecordingClient(lambda p, q: HEAD + "</feed>")
        supplier_connector.fetch_all_suppliers_with_related(c, top=10, page_size=10, ordered=True)
        self.assertNotIn("$filter", c.calls[0][1])
        self.assertIn("$orderby", c.calls[0][1])

    def test_rejected_filter_falls_back_to_unordered_full_fetch(self):
        def handler(p, q):
            if "$filter" in q or "$orderby" in q:
                raise http_error()
            return HEAD + entry(Supplier="S1") + "</feed>"
        c = RecordingClient(handler)
        data = supplier_connector.fetch_all_suppliers_with_related(c, top=10, page_size=10, watermark=WM)
        self.assertEqual(len(data["suppliers"]), 1)
        self.assertFalse(data["_ordered"], "an unordered result must never advance the watermark")

    def test_quota_attaches_the_suppliers_fetched_so_far(self):
        state = {"n": 0}
        def handler(p, q):
            if "to_Supplier" in p:               # child look-ups succeed
                return HEAD + "</feed>"
            state["n"] += 1                      # supplier pages: 1st ok, 2nd hits the quota
            if state["n"] == 1:
                return HEAD + entry(Supplier="S1") + entry(Supplier="S2") + "</feed>"
            raise SAPQuotaExceeded("quota")
        c = RecordingClient(handler)
        with self.assertRaises(SAPQuotaExceeded) as ctx:
            supplier_connector.fetch_all_suppliers_with_related(c, top=100, page_size=2, use_expand=False)
        self.assertEqual([s["Supplier"] for s in ctx.exception.partial["suppliers"]], ["S1", "S2"])


class TestPurchaseOrderConnectorIncremental(unittest.TestCase):
    def test_filter_combines_supplier_chunk_and_watermark(self):
        c = RecordingClient(lambda p, q: {"value": []})
        purchase_order_connector.fetch_purchase_orders(c, ["S1", "S2"], watermark=WM)
        flt = c.calls[0][1]["$filter"]
        self.assertEqual(flt, "(Supplier eq 'S1' or Supplier eq 'S2') and "
                              "(LastChangeDateTime ge 2026-10-24T07:30:05Z)")

    def test_complete_flag(self):
        stats = {}
        c = RecordingClient(lambda p, q: {"value": [{"PurchaseOrder": "P"}]})
        purchase_order_connector.fetch_purchase_orders(c, [f"S{i}" for i in range(3)], chunk_size=1,
                                                       top=100, stats=stats)
        self.assertTrue(stats["complete"])
        stats = {}
        purchase_order_connector.fetch_purchase_orders(c, [f"S{i}" for i in range(3)], chunk_size=1,
                                                       top=1, stats=stats)
        self.assertFalse(stats["complete"], "top reached -> watermark must not advance")

    def test_rejected_filter_retries_the_chunk_unfiltered(self):
        def handler(p, q):
            if "ge" in q["$filter"]:
                raise http_error()
            return {"value": [{"PurchaseOrder": "P1"}]}
        stats = {}
        c = RecordingClient(handler)
        rows = purchase_order_connector.fetch_purchase_orders(c, ["S1"], watermark=WM, stats=stats)
        self.assertEqual(len(rows), 1)
        self.assertTrue(stats["filter_dropped"])

    def test_missing_chunk_marks_run_incomplete(self):
        stats = {}
        c = RecordingClient(lambda p, q: (_ for _ in ()).throw(http_error()))
        purchase_order_connector.fetch_purchase_orders(c, ["S1"], stats=stats)
        self.assertFalse(stats["complete"])


class TestIntegrityWithDatabaseKeys(unittest.TestCase):
    ARGS = dict(suppliers=[], companies=[], purch_orgs=[], texts=[], orders=[], items=[],
                invoices=[], po_refs=[])

    def run_it(self, **kw):
        args = {**self.ARGS, **kw}
        return enforce_integrity(**args)

    def test_po_of_supplier_loaded_earlier_is_kept(self):
        po = PurchaseOrder("P1", supplier="S1")
        clean, report = self.run_it(orders=[po], known={"suppliers": {"S1"}})
        self.assertEqual(clean["orders"], [po])
        self.assertEqual(report, {})

    def test_without_known_keys_it_is_still_dropped(self):
        clean, report = self.run_it(orders=[PurchaseOrder("P1", supplier="S1")])
        self.assertEqual(clean["orders"], [])

    def test_item_and_reference_use_db_parents(self):
        it = PurchaseOrderItem("P1", "10")
        ref = InvoicePOReference("I1", "2026", "P1", "10", "1")
        clean, report = self.run_it(items=[it], po_refs=[ref],
                                    known={"orders": {"P1"}, "items": {("P1", "10")},
                                           "invoices": {("I1", "2026")}})
        self.assertEqual((clean["items"], clean["po_refs"]), ([it], [ref]))
        self.assertEqual(report, {})

    def test_details_name_the_dropped_rows(self):
        details = {}
        ref = InvoicePOReference("I9", "2026", "P1", "10", "1")
        _, report = self.run_it(po_refs=[ref], details=details)
        reason = "invoice_po_reference: invoice header missing (dropped)"
        self.assertEqual(report[reason], 1)
        self.assertEqual(details[reason], [str(("I9", "2026", "P1", "10", "1"))])

    def test_details_are_capped(self):
        details = {}
        refs = [InvoicePOReference(f"I{i}", "2026", "P1", "10", "1") for i in range(50)]
        _, report = self.run_it(po_refs=refs, details=details)
        reason = "invoice_po_reference: invoice header missing (dropped)"
        self.assertEqual(report[reason], 50)
        self.assertEqual(len(details[reason]), 20)


if __name__ == "__main__":
    unittest.main()
