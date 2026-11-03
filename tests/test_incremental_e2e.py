"""
End-to-end test of the incremental sync: the real ``app.main.run()`` against a
real PostgreSQL, with a *fake SAP server* in place of the HTTP client.

The fake understands $filter (``<field> ge <literal>``, ``Supplier eq 'x' or ...``),
$orderby, $top/$skip and $expand, and can be told to reject date filters or to
hit the quota - so the scenarios below cover:

  1. first run                      -> everything loaded, watermarks stored
  2. re-run, nothing changed        -> only boundary rows re-downloaded, 0 updates, 0 change-log rows
  3. new / changed records          -> inserted / updated, change_log has old+new values and the run id,
                                       children of earlier-run parents are NOT dropped (step 4),
                                       POs of a brand-new supplier behind the watermark still arrive
  4. quota error in stage 2         -> stage 1 stays committed, run_log says QUOTA, next run resumes
  5. SAP rejects the date filter    -> warning + full-fetch fallback, data still correct

Needs PostgreSQL (defaults: localhost, postgres/postgres, database sap_connector;
override with PG_HOST / PG_PORT / PG_USER / PG_PASSWORD / PG_DATABASE).
The whole module is skipped when PostgreSQL cannot be reached.
WARNING: it DROPs and re-creates the connector's tables in that database.
"""

import contextlib
import io
import os
import re
import unittest
from pathlib import Path
from unittest import mock

import psycopg2
import requests

from app import main as app_main
from app.config import AppConfig, PGConfig, SAPConfig
from app.connectors.invoice_connector import INV_HEADER_PATH, INV_PO_REF_PATH
from app.connectors.purchase_order_connector import PO_ITEM_PATH, PO_PATH
from app.connectors.supplier_connector import SUPPLIER_PATH
from app.mapping.mappers import _timestamp
from app.sap_client import SAPQuotaExceeded

ROOT = Path(__file__).resolve().parent.parent
PG = PGConfig(
    host=os.getenv("PG_HOST", "localhost"),
    port=int(os.getenv("PG_PORT", "5432")),
    database=os.getenv("PG_DATABASE", "sap_connector"),
    user=os.getenv("PG_USER", "postgres"),
    password=os.getenv("PG_PASSWORD", "postgres"),
)


def _connect():
    return psycopg2.connect(host=PG.host, port=PG.port, dbname=PG.database,
                            user=PG.user, password=PG.password)


def _pg_available() -> bool:
    try:
        _connect().close()
        return True
    except psycopg2.Error:
        return False


# ----------------------------------------------------------------------
# Fake SAP
# ----------------------------------------------------------------------

NS = ('xmlns="http://www.w3.org/2005/Atom" '
      'xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata" '
      'xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices"')


def _props_xml(props: dict) -> str:
    return "".join(f"<d:{k}>{v}</d:{k}>" for k, v in props.items())


def _entry_xml(props: dict, nav: dict | None = None) -> str:
    links = ""
    for name, rows in (nav or {}).items():
        kids = "".join(_entry_xml(r) for r in rows)
        links += f'<link title="{name}"><m:inline><feed>{kids}</feed></m:inline></link>'
    return (f'<entry>{links}<content type="application/xml"><m:properties>'
            f'{_props_xml(props)}</m:properties></content></entry>')


def http_400():
    r = requests.Response()
    r.status_code = 400
    return requests.HTTPError("400 Bad Request", response=r)


class FakeSAP:
    def __init__(self):
        self.suppliers, self.pos, self.items = {}, {}, []
        self.refs, self.invoices = [], {}
        self.request_count = 0
        self.rows_served = 0
        self.reject_date_filter = False
        self.quota_on_po = False

    # ---- helpers ------------------------------------------------------
    def _select(self, rows, params, key_field):
        flt = params.get("$filter", "")
        m = re.search(r"(\w+) ge (?:datetimeoffset|datetime)?'?([0-9T:\-.Z]+)'?", flt)
        if m:
            if self.reject_date_filter:
                raise http_400()
            field, value = m.group(1), _timestamp(m.group(2))
            rows = [r for r in rows if r.get(field) and _timestamp(r[field]) >= value]
        order = params.get("$orderby")
        if order:
            if self.reject_date_filter:
                raise http_400()
            fields = [p.split()[0] for p in order.split(",")]
            rows = sorted(rows, key=lambda r: tuple(str(r.get(f, "")) for f in fields))
        skip, top = int(params.get("$skip", 0)), int(params["$top"])
        page = rows[skip:skip + top]
        self.rows_served += len(page)
        return page

    @staticmethod
    def _or_values(flt, field):
        return set(re.findall(rf"{field} eq '([^']+)'", flt))

    # ---- client interface (used by app.odata paging) -------------------
    def get_xml(self, path, params=None):
        self.request_count += 1
        params = dict(params or {})
        if path == SUPPLIER_PATH:
            page = self._select(list(self.suppliers.values()), params, "Supplier")
            expand = "$expand" in params
            body = ""
            for s in page:
                nav = None
                if expand:
                    nav = {"to_SupplierCompany": [{"Supplier": s["Supplier"], "CompanyCode": "1010",
                                                   "CompanyName": f"{s['SupplierName']} Co"}],
                           "to_SupplierPurchasingOrg": [],
                           "to_SupplierText": []}
                body += _entry_xml(s, nav)
            return f"<feed {NS}>{body}</feed>".encode()
        if path == INV_PO_REF_PATH:
            pos = self._or_values(params.get("$filter", ""), "PurchaseOrder")
            page = self._select([r for r in self.refs if r["PurchaseOrder"] in pos], params, "")
            return f"<feed {NS}>{''.join(_entry_xml(r) for r in page)}</feed>".encode()
        if path == INV_HEADER_PATH:
            flt = params.get("$filter", "")
            keys = set(re.findall(r"SupplierInvoice eq '([^']+)' and FiscalYear eq '([^']+)'", flt))
            page = self._select([h for k, h in self.invoices.items() if k in keys], params, "")
            return f"<feed {NS}>{''.join(_entry_xml(h) for h in page)}</feed>".encode()
        raise AssertionError(f"unexpected XML path {path}")

    def get_json(self, path, params=None):
        self.request_count += 1
        params = dict(params or {})
        if self.quota_on_po:
            raise SAPQuotaExceeded("quota used up (fake)")
        flt = params.get("$filter", "")
        if path == PO_PATH:
            sup = self._or_values(flt, "Supplier")
            rows = [p for p in self.pos.values() if p["Supplier"] in sup]
            return {"value": self._select(rows, params, "PurchaseOrder")}
        if path == PO_ITEM_PATH:
            pos = self._or_values(flt, "PurchaseOrder")
            rows = [i for i in self.items if i["PurchaseOrder"] in pos]
            return {"value": self._select(rows, params, "")}
        raise AssertionError(f"unexpected JSON path {path}")


def sup(sid, name, changed):
    return {"Supplier": sid, "SupplierName": name, "CreationDate": "2026-01-01T00:00:00",
            "LastChangeDateTime": changed}


def po(pid, supplier, changed, otype="NB"):
    return {"PurchaseOrder": pid, "Supplier": supplier, "PurchaseOrderType": otype,
            "CreationDate": "2026-01-01", "LastChangeDateTime": changed}


def item(pid, no="10"):
    return {"PurchaseOrder": pid, "PurchaseOrderItem": no, "Material": f"MAT-{pid}"}


# ----------------------------------------------------------------------

@unittest.skipUnless(_pg_available(), "PostgreSQL is not reachable - e2e tests skipped")
class TestIncrementalEndToEnd(unittest.TestCase):

    def setUp(self):
        # clean slate: (re)create the 8 data tables, drop the history tables
        conn = _connect()
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS change_log, run_log, sync_state CASCADE")
            cur.execute((ROOT / "sql" / "schema.sql").read_text(encoding="utf-8"))
        conn.commit()
        conn.close()

        self.fake = FakeSAP()
        f = self.fake
        for s in (sup("S1", "Alpha", "2026-01-01T10:00:00Z"),
                  sup("S2", "Beta", "2026-02-01T10:00:00Z"),
                  sup("S3", "Gamma", "2026-03-01T10:00:00Z")):
            f.suppliers[s["Supplier"]] = s
        for p, s, ch in (("P1", "S1", "2026-01-05T09:00:00Z"),
                         ("P2", "S2", "2026-02-05T09:00:00Z"),
                         ("P3", "S3", "2026-03-05T09:00:00Z")):
            f.pos[p] = po(p, s, ch)
            f.items.append(item(p))
        f.refs.append({"SupplierInvoice": "I1", "FiscalYear": "2026", "PurchaseOrder": "P1",
                       "PurchaseOrderItem": "10", "SupplierInvoiceItem": "1"})
        f.invoices[("I1", "2026")] = {"SupplierInvoice": "I1", "FiscalYear": "2026",
                                      "InvoicingParty": "S1"}

        self.cfg = AppConfig(
            sap=SAPConfig(
                base_url="http://fake", api_key="", username="", password="", auth_mode="none",
                supplier_top=100, po_top=100, invoice_top=100, item_top=100,
                page_size=50, filter_chunk=20, request_delay=0.0,
                incremental=True, full_refresh=False,
                supplier_date_field="LastChangeDateTime", supplier_date_type="datetimeoffset",
                po_date_field="LastChangeDateTime", po_date_type="datetimeoffset",
            ),
            pg=PG,
        )
        self.out = ""

    # ---- helpers ------------------------------------------------------
    def run_app(self, **sap_overrides):
        cfg = self.cfg
        if sap_overrides:
            from dataclasses import replace
            cfg = AppConfig(sap=replace(cfg.sap, **sap_overrides), pg=cfg.pg)
        self.fake.rows_served = 0
        buf = io.StringIO()
        with mock.patch.object(app_main, "load_config", lambda: cfg), \
             mock.patch.object(app_main, "SAPClient", lambda c: self.fake), \
             contextlib.redirect_stdout(buf):
            try:
                app_main.run()
            finally:
                self.out = buf.getvalue()

    def q(self, sql, args=None):
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, args)
                return cur.fetchall()
        finally:
            conn.close()

    def count(self, table):
        return self.q(f"SELECT COUNT(*) FROM {table}")[0][0]

    def last_run(self):
        return self.q("SELECT run_id::text, status, stats, dropped FROM run_log "
                      "ORDER BY started_at DESC LIMIT 1")[0]

    # ---- 1. first run ---------------------------------------------------
    def test_1_first_run_loads_everything_and_stores_watermarks(self):
        self.run_app()
        self.assertEqual((self.count("supplier"), self.count("purchase_order"),
                          self.count("purchase_order_item"), self.count("supplier_invoice"),
                          self.count("invoice_po_reference"), self.count("supplier_company")),
                         (3, 3, 3, 1, 1, 3))
        wm = dict(self.q("SELECT entity, last_value FROM sync_state"))
        self.assertEqual(str(wm["supplier"]), "2026-03-01 10:00:00")
        self.assertEqual(str(wm["purchase_order"]), "2026-03-05 09:00:00")
        _, status, stats, _ = self.last_run()
        self.assertEqual(status, "OK")
        self.assertEqual(stats["supplier"]["inserted"], 3)
        self.assertEqual(self.count("change_log"), 0)  # inserts are not logged

    # ---- 2. re-run with nothing new -------------------------------------
    def test_2_rerun_downloads_little_and_changes_nothing(self):
        self.run_app()
        first_served = self.fake.rows_served
        self.run_app()
        # only the boundary rows (>= watermark) come back, not all of them
        self.assertLess(self.fake.rows_served, first_served)
        _, status, stats, _ = self.last_run()
        self.assertEqual(status, "OK")
        for table, s in stats.items():
            self.assertEqual((s["inserted"], s["updated"]), (0, 0), table)
        self.assertEqual(self.count("change_log"), 0)
        self.assertEqual((self.count("supplier"), self.count("purchase_order")), (3, 3))

    # ---- 3. new + changed records ----------------------------------------
    def test_3_new_and_changed_records(self):
        self.run_app()
        f = self.fake
        # S2 renamed (changed in SAP), brand-new supplier S4 with an OLD PO (behind the watermark)
        f.suppliers["S2"] = sup("S2", "Beta Limited", "2026-04-01T10:00:00Z")
        f.suppliers["S4"] = sup("S4", "Delta", "2026-04-02T10:00:00Z")
        f.pos["P4"] = po("P4", "S4", "2026-01-01T09:00:00Z")      # older than the PO watermark!
        f.items.append(item("P4"))
        # P2 changed; P5 is a new PO of S1 - S1 itself is NOT fetched this run (Step 4)
        f.pos["P2"] = po("P2", "S2", "2026-04-03T09:00:00Z", otype="FO")
        f.pos["P5"] = po("P5", "S1", "2026-04-04T09:00:00Z")
        f.items.append(item("P5"))

        self.run_app()
        run_id, status, stats, dropped = self.last_run()
        self.assertEqual(status, "OK")

        self.assertEqual(self.q("SELECT supplier_name FROM supplier WHERE supplier='S2'")[0][0], "Beta Limited")
        self.assertEqual(self.q("SELECT purchase_order_type FROM purchase_order WHERE purchase_order='P2'")[0][0], "FO")
        ids = {r[0] for r in self.q("SELECT purchase_order FROM purchase_order")}
        self.assertIn("P4", ids, "PO of a brand-new supplier behind the watermark must still be loaded")
        self.assertIn("P5", ids, "PO whose supplier was loaded by an earlier run must not be dropped")
        self.assertEqual(dropped, {})

        # change log: only the real changes, with old/new values and this run's id
        rows = self.q("SELECT table_name, record_key, changed_fields, run_id::text FROM change_log ORDER BY id")
        by_table = {r[0]: r for r in rows}
        self.assertEqual(set(by_table), {"supplier", "supplier_company", "purchase_order"})
        _, key, fields, rid = by_table["supplier"]
        self.assertEqual(key, {"supplier": "S2"})
        self.assertEqual(fields["supplier_name"], {"old": "Beta", "new": "Beta Limited"})
        self.assertEqual(rid, run_id)
        self.assertEqual(by_table["purchase_order"][2]["purchase_order_type"], {"old": "NB", "new": "FO"})
        self.assertEqual(stats["supplier"]["inserted"], 1)   # S4
        self.assertEqual(stats["supplier"]["updated"], 1)    # S2

    # ---- 4. quota in stage 2 ----------------------------------------------
    def test_4_quota_in_stage_2_keeps_stage_1_and_next_run_resumes(self):
        self.run_app()
        f = self.fake
        f.suppliers["S5"] = sup("S5", "Epsilon", "2026-05-01T10:00:00Z")
        f.pos["P6"] = po("P6", "S5", "2026-05-02T09:00:00Z")
        f.items.append(item("P6"))

        f.quota_on_po = True
        with self.assertRaises(SAPQuotaExceeded):
            self.run_app()
        self.assertEqual(self.last_run()[1], "QUOTA")
        self.assertEqual(self.q("SELECT COUNT(*) FROM supplier WHERE supplier='S5'")[0][0], 1,
                         "stage 1 (suppliers) must be committed even though stage 2 failed")
        wm = dict(self.q("SELECT entity, last_value FROM sync_state"))
        self.assertEqual(str(wm["supplier"]), "2026-05-01 10:00:00")
        self.assertEqual(str(wm["purchase_order"]), "2026-03-05 09:00:00", "PO watermark must not move")
        self.assertEqual(self.q("SELECT COUNT(*) FROM purchase_order WHERE purchase_order='P6'")[0][0], 0)

        f.quota_on_po = False
        self.run_app()
        self.assertEqual(self.last_run()[1], "OK")
        self.assertEqual(self.q("SELECT COUNT(*) FROM purchase_order WHERE purchase_order='P6'")[0][0], 1,
                         "S5 was already stored, so its PO is picked up by the watermark filter")

    # ---- 5. SAP rejects the date filter ---------------------------------
    def test_5_rejected_date_filter_falls_back_to_full_fetch(self):
        self.run_app()
        f = self.fake
        f.suppliers["S2"] = sup("S2", "Beta Limited", "2026-04-01T10:00:00Z")
        f.reject_date_filter = True
        self.run_app()
        self.assertIn("rejected the supplier date filter", self.out)
        self.assertEqual(self.last_run()[1], "OK")
        self.assertEqual(self.q("SELECT supplier_name FROM supplier WHERE supplier='S2'")[0][0], "Beta Limited")
        self.assertEqual(self.count("supplier"), 3)

    # ---- 6. FULL_REFRESH / INCREMENTAL=false -------------------------------
    def test_6_full_refresh_ignores_the_watermark(self):
        self.run_app()
        self.run_app()
        incr_served = self.fake.rows_served
        self.run_app(full_refresh=True)
        self.assertGreater(self.fake.rows_served, incr_served)
        self.assertEqual(self.q("SELECT mode FROM run_log ORDER BY started_at DESC LIMIT 1")[0][0], "full")


if __name__ == "__main__":
    unittest.main()
