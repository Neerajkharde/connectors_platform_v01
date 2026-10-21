"""Connector tests: call counts (chunking), $expand fallback, quota propagation."""

import unittest

import requests

from app.connectors import invoice_connector, purchase_order_connector, supplier_connector
from app.sap_client import SAPQuotaExceeded
from tests.test_odata import HEAD, entry


class RecordingClient:
    """Records calls; behaviour supplied by a handler(path, params) -> bytes | dict."""
    def __init__(self, handler):
        self.handler, self.calls = handler, []

    def get_xml(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        return self.handler(path, params or {})

    get_json = get_xml


def http_error():
    r = requests.Response()
    r.status_code = 400
    return requests.HTTPError("bad", response=r)


class TestChunking(unittest.TestCase):
    def test_purchase_orders_use_one_call_per_chunk_not_per_supplier(self):
        c = RecordingClient(lambda p, q: {"value": []})
        purchase_order_connector.fetch_purchase_orders(c, [f"S{i}" for i in range(45)], chunk_size=20)
        self.assertEqual(len(c.calls), 3)  # 45 suppliers -> 3 calls (old code: 45)
        self.assertIn("Supplier eq 'S0' or Supplier eq 'S1'", c.calls[0][1]["$filter"])

    def test_po_item_and_ref_calls_are_chunked(self):
        c = RecordingClient(lambda p, q: {"value": []})
        purchase_order_connector.fetch_purchase_order_items(c, [f"P{i}" for i in range(41)], chunk_size=20)
        self.assertEqual(len(c.calls), 3)
        c2 = RecordingClient(lambda p, q: HEAD + "</feed>")
        invoice_connector.fetch_invoice_po_refs(c2, [f"P{i}" for i in range(41)], chunk_size=20)
        self.assertEqual(len(c2.calls), 3)

    def test_invoice_headers_fetched_by_key_group(self):
        c = RecordingClient(lambda p, q: HEAD + entry(SupplierInvoice="I1", FiscalYear="2026") + "</feed>")
        invoice_connector.fetch_invoice_headers(c, {("I1", "2026"), ("I2", "2026")}, chunk_size=10)
        self.assertEqual(len(c.calls), 1)
        self.assertIn("(SupplierInvoice eq 'I1' and FiscalYear eq '2026')", c.calls[0][1]["$filter"])

    def test_http_error_in_one_chunk_does_not_abort_others(self):
        state = {"n": 0}
        def handler(p, q):
            state["n"] += 1
            if state["n"] == 1:
                raise http_error()
            return {"value": [{"PurchaseOrder": "X"}]}
        c = RecordingClient(handler)
        rows = purchase_order_connector.fetch_purchase_orders(c, [f"S{i}" for i in range(40)], chunk_size=20)
        self.assertEqual(len(rows), 1)  # 2nd chunk still fetched


class TestQuotaPropagation(unittest.TestCase):
    def _raise_quota(self, *_):
        raise SAPQuotaExceeded("quota")

    def test_quota_is_not_swallowed_by_any_connector(self):
        c = RecordingClient(self._raise_quota)
        with self.assertRaises(SAPQuotaExceeded):
            purchase_order_connector.fetch_purchase_orders(c, ["S1"])
        with self.assertRaises(SAPQuotaExceeded):
            purchase_order_connector.fetch_purchase_order_items(c, ["P1"])
        with self.assertRaises(SAPQuotaExceeded):
            invoice_connector.fetch_invoice_po_refs(c, ["P1"])
        with self.assertRaises(SAPQuotaExceeded):
            invoice_connector.fetch_invoice_headers(c, {("I", "2026")})
        with self.assertRaises(SAPQuotaExceeded):
            supplier_connector.fetch_all_suppliers_with_related(c)
        self.assertEqual(len(c.calls), 5)  # one call each, no retry storm


class TestSupplierExpandFallback(unittest.TestCase):
    def test_falls_back_to_per_supplier_calls_when_expand_is_rejected(self):
        def handler(path, params):
            if "$expand" in params:
                raise http_error()
            if path.endswith("A_Supplier"):
                return HEAD + entry(Supplier="1") + "</feed>"
            return HEAD + entry(CompanyCode="1710") + "</feed>"
        c = RecordingClient(handler)
        data = supplier_connector.fetch_all_suppliers_with_related(c, top=10, page_size=10)
        self.assertEqual(len(data["suppliers"]), 1)
        self.assertEqual(data["companies"][0]["Supplier"], "1")  # parent key injected into child rows

    def test_expand_path_uses_one_call_for_all_suppliers(self):
        inline = lambda nav: (f'<link title="{nav}" href="h"><m:inline>' + HEAD + entry(CompanyCode="1710")
                              + "</feed></m:inline></link>")
        def handler(path, params):
            ents = ""
            for sid in ("1", "2", "3"):
                ents += ("<entry>" + "".join(inline(n) for n in supplier_connector.NAV_TARGETS)
                         + f'<content><m:properties><d:Supplier>{sid}</d:Supplier></m:properties></content></entry>')
            return HEAD + ents + "</feed>"
        c = RecordingClient(handler)
        data = supplier_connector.fetch_all_suppliers_with_related(c, top=10, page_size=10)
        self.assertEqual(len(c.calls), 1)  # old code: 1 + 3*3 = 10
        self.assertEqual(len(data["companies"]), 3)


if __name__ == "__main__":
    unittest.main()
