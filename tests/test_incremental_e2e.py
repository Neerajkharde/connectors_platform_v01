"""
End-to-end test of the incremental sync: the real ``app.main.run()`` against a
real PostgreSQL, with a *fake SAP server* in place of the HTTP client.

The fake evaluates real OData filters ($filter with and/or/parentheses and
eq/gt/ge, $orderby, $top/$skip, $expand), and can be told to reject date
filters or to hit the quota, so the scenarios cover:

  1. first run                       -> everything loaded, cursors stored
  2. re-run, nothing changed         -> nothing re-downloaded, 0 updates, 0 change-log rows
  3. new / changed records           -> inserted / updated, change_log has old+new values and run id,
                                        PO of a brand-new supplier (old date) and PO of an earlier-run
                                        supplier are loaded, nothing dropped
  4. quota error in the PO stage     -> suppliers stay committed, next run resumes
  5. SAP rejects the date filter     -> warnings + full-fetch fallback, data still correct
  6. FULL_REFRESH                    -> re-reads everything
  7. PO budget (PO_TOP) + batches    -> run stops at the budget, next runs continue until done
  8. many POs with the SAME timestamp-> keyset paging still moves forward (no stall)
  9. quota between two batches       -> finished batch kept, only the in-flight batch is redone
 10. many suppliers with the same date, small SUPPLIER_TOP -> keyset paging for suppliers

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
from datetime import datetime, timedelta, timezone
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


_TOKEN = re.compile(
    r"\s*(?P<p>[()])|\s*(?P<bool>and|or)\b"
    r"|\s*(?P<f>\w+)\s+(?P<op>eq|ge|gt)\s+(?P<v>(?:datetimeoffset|datetime)'[^']*'|'(?:[^']|'')*'|[^\s()]+)")


def _literal(raw):
    m = re.match(r"(?:datetimeoffset|datetime)'([^']*)'$", raw)
    if m:
        return _timestamp(m.group(1))
    if raw.startswith("'"):
        return raw[1:-1].replace("''", "'")
    return _timestamp(raw)


def compile_filter(text):
    """Tiny OData $filter evaluator: and / or / parentheses / eq ge gt."""
    tokens = [m for m in _TOKEN.finditer(text)]
    pos = [0]

    def peek():
        return tokens[pos[0]] if pos[0] < len(tokens) else None

    def atom():
        t = tokens[pos[0]]; pos[0] += 1
        if t.group("p") == "(":
            f = disj()
            pos[0] += 1  # ')'
            return f
        field, op, lit = t.group("f"), t.group("op"), _literal(t.group("v"))
        def cmp(row):
            left = row.get(field)
            if isinstance(lit, datetime):
                left = _timestamp(left) if left else None
            if left is None:
                return False
            return {"eq": left == lit, "ge": left >= lit, "gt": left > lit}[op]
        return cmp

    def conj():
        f = atom()
        while peek() is not None and peek().group("bool") == "and":
            pos[0] += 1; g = atom(); f = (lambda a, b: lambda r: a(r) and b(r))(f, g)
        return f

    def disj():
        f = conj()
        while peek() is not None and peek().group("bool") == "or":
            pos[0] += 1; g = conj(); f = (lambda a, b: lambda r: a(r) or b(r))(f, g)
        return f

    return disj()


class FakeSAP:
    def __init__(self):
        self.suppliers, self.pos, self.items = {}, {}, []
        self.refs, self.invoices = [], {}
        self.request_count = 0
        self.rows_served = 0
        self.reject_date_filter = False
        self.quota_on_po = False
        self.po_calls = 0
        self.quota_after_po_calls = None   # raise quota once more PO-header calls than this were made

    # ---- helpers ------------------------------------------------------
    def _select(self, rows, params):
        flt = params.get("$filter", "")
        order = params.get("$orderby")
        if self.reject_date_filter and (order or re.search(r"\b(ge|gt)\b", flt)):
            raise http_400()
        if flt:
            pred = compile_filter(flt)
            rows = [r for r in rows if pred(r)]
        if order:
            fields = [p.split()[0] for p in order.split(",")]
            rows = sorted(rows, key=lambda r: tuple(str(r.get(f, "")) for f in fields))
        skip, top = int(params.get("$skip", 0)), int(params["$top"])
        page = rows[skip:skip + top]
        self.rows_served += len(page)
        return page

    # ---- client interface (used by app.odata paging) -------------------
    def get_xml(self, path, params=None):
        self.request_count += 1
        params = dict(params or {})
        if path == SUPPLIER_PATH:
            page = self._select(list(self.suppliers.values()), params)
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
            page = self._select(self.refs, params)
            return f"<feed {NS}>{''.join(_entry_xml(r) for r in page)}</feed>".encode()
        if path == INV_HEADER_PATH:
            page = self._select(list(self.invoices.values()), params)
            return f"<feed {NS}>{''.join(_entry_xml(h) for h in page)}</feed>".encode()
        raise AssertionError(f"unexpected XML path {path}")

    def get_json(self, path, params=None):
        self.request_count += 1
        params = dict(params or {})
        if self.quota_on_po:
            raise SAPQuotaExceeded("quota used up (fake)")
        if path == PO_PATH:
            self.po_calls += 1
            if self.quota_after_po_calls is not None and self.po_calls > self.quota_after_po_calls:
                raise SAPQuotaExceeded("quota used up (fake)")
            return {"value": self._select(list(self.pos.values()), params)}
        if path == PO_ITEM_PATH:
            return {"value": self._select(self.items, params)}
        raise AssertionError(f"unexpected JSON path {path}")


NOW = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def ago(days, hours=0):
    """SAP-style UTC timestamp `days` before the real clock (cursor logic depends on 'now')."""
    return (NOW - timedelta(days=days, hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


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
            cur.execute("DROP TABLE IF EXISTS change_log, run_log, sync_state, supplier_po_cursor CASCADE")
            cur.execute((ROOT / "sql" / "schema.sql").read_text(encoding="utf-8"))
        conn.commit()
        conn.close()

        self.fake = FakeSAP()
        f = self.fake
        for s_ in (sup("S1", "Alpha", ago(300)), sup("S2", "Beta", ago(200)), sup("S3", "Gamma", ago(100))):
            f.suppliers[s_["Supplier"]] = s_
        for p_, s_, ch in (("P1", "S1", ago(290)), ("P2", "S2", ago(190)), ("P3", "S3", ago(90))):
            f.pos[p_] = po(p_, s_, ch)
            f.items.append(item(p_))
        f.refs.append({"SupplierInvoice": "I1", "FiscalYear": "2026", "PurchaseOrder": "P1",
                       "PurchaseOrderItem": "10", "SupplierInvoiceItem": "1"})
        f.invoices[("I1", "2026")] = {"SupplierInvoice": "I1", "FiscalYear": "2026",
                                      "InvoicingParty": "S1"}

        self.cfg = AppConfig(
            sap=SAPConfig(
                base_url="http://fake", api_key="", username="", password="", auth_mode="none",
                supplier_top=100, po_top=100, invoice_top=100, item_top=100,
                page_size=50, filter_chunk=20, request_delay=0.0, po_batch=500,
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

    def cursor_of(self, supplier):
        r = self.q("SELECT last_value, last_key FROM supplier_po_cursor WHERE supplier=%s", (supplier,))
        return r[0] if r else None

    def po_ids(self):
        return {r[0] for r in self.q("SELECT purchase_order FROM purchase_order")}

    # ---- 1. first run ---------------------------------------------------
    def test_1_first_run_loads_everything_and_stores_cursors(self):
        self.run_app()
        self.assertEqual((self.count("supplier"), self.count("purchase_order"),
                          self.count("purchase_order_item"), self.count("supplier_invoice"),
                          self.count("invoice_po_reference"), self.count("supplier_company")),
                         (3, 3, 3, 1, 1, 3))
        sup_wm = self.q("SELECT last_value, last_key FROM sync_state WHERE entity='supplier'")[0]
        self.assertEqual((str(sup_wm[0])[:10], sup_wm[1]), (str(NOW - timedelta(days=100))[:10], "S3"))
        for sid in ("S1", "S2", "S3"):
            self.assertIsNotNone(self.cursor_of(sid), f"PO cursor of {sid}")
        _, status, stats, _ = self.last_run()
        self.assertEqual(status, "OK")
        self.assertEqual(stats["supplier"]["inserted"], 3)
        self.assertEqual(stats["purchase_order"]["inserted"], 3)
        self.assertEqual(self.count("change_log"), 0)  # inserts are not logged

    # ---- 2. re-run with nothing new -------------------------------------
    def test_2_rerun_downloads_nothing_and_changes_nothing(self):
        self.run_app()
        first_served = self.fake.rows_served
        self.run_app()
        self.assertGreater(first_served, 0)
        self.assertEqual(self.fake.rows_served, 0, "nothing is new -> no row is downloaded again")
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
        # S2 renamed (changed in SAP), brand-new supplier S4 with an OLD PO (behind every cursor)
        f.suppliers["S2"] = sup("S2", "Beta Limited", ago(0, 5))
        f.suppliers["S4"] = sup("S4", "Delta", ago(0, 4))
        f.pos["P4"] = po("P4", "S4", ago(250))
        f.items.append(item("P4"))
        # P2 changed; P5 is a new PO of S1 - S1 itself is NOT fetched this run
        f.pos["P2"] = po("P2", "S2", ago(0, 3), otype="FO")
        f.pos["P5"] = po("P5", "S1", ago(0, 2))
        f.items.append(item("P5"))

        self.run_app()
        run_id, status, stats, dropped = self.last_run()
        self.assertEqual(status, "OK")

        self.assertEqual(self.q("SELECT supplier_name FROM supplier WHERE supplier='S2'")[0][0], "Beta Limited")
        self.assertEqual(self.q("SELECT purchase_order_type FROM purchase_order WHERE purchase_order='P2'")[0][0], "FO")
        self.assertIn("P4", self.po_ids(), "old PO of a brand-new supplier must still be loaded")
        self.assertIn("P5", self.po_ids(), "PO whose supplier was loaded by an earlier run must not be dropped")
        self.assertEqual(dropped, {})

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

    # ---- 4. quota in the PO stage -----------------------------------------
    def test_4_quota_in_po_stage_keeps_suppliers_and_next_run_resumes(self):
        self.run_app()
        f = self.fake
        f.suppliers["S5"] = sup("S5", "Epsilon", ago(0, 5))
        f.pos["P6"] = po("P6", "S5", ago(0, 4))
        f.items.append(item("P6"))

        f.quota_on_po = True
        with self.assertRaises(SAPQuotaExceeded):
            self.run_app()
        self.assertEqual(self.last_run()[1], "QUOTA")
        self.assertEqual(self.q("SELECT COUNT(*) FROM supplier WHERE supplier='S5'")[0][0], 1,
                         "suppliers must be committed even though the PO stage failed")
        self.assertNotIn("P6", self.po_ids())
        self.assertIsNone(self.cursor_of("S5"), "no PO cursor may move without its batch")

        f.quota_on_po = False
        self.run_app()
        self.assertEqual(self.last_run()[1], "OK")
        self.assertIn("P6", self.po_ids())

    # ---- 5. SAP rejects the date filter ---------------------------------
    def test_5_rejected_date_filter_falls_back_to_full_fetch(self):
        self.run_app()
        f = self.fake
        f.suppliers["S2"] = sup("S2", "Beta Limited", ago(0, 5))
        f.pos["P2"] = po("P2", "S2", ago(0, 3), otype="FO")
        f.reject_date_filter = True
        self.run_app()
        self.assertIn("rejected the supplier date filter", self.out)
        self.assertIn("rejected the PO date filter", self.out)
        self.assertEqual(self.last_run()[1], "OK")
        self.assertEqual(self.q("SELECT supplier_name FROM supplier WHERE supplier='S2'")[0][0], "Beta Limited")
        self.assertEqual(self.q("SELECT purchase_order_type FROM purchase_order WHERE purchase_order='P2'")[0][0], "FO")
        self.assertEqual(self.count("supplier"), 3)

    # ---- 6. FULL_REFRESH ---------------------------------------------------
    def test_6_full_refresh_ignores_the_cursors(self):
        self.run_app()
        self.run_app()
        self.assertEqual(self.fake.rows_served, 0)
        self.run_app(full_refresh=True)
        self.assertGreater(self.fake.rows_served, 0)
        self.assertEqual(self.q("SELECT mode FROM run_log ORDER BY started_at DESC LIMIT 1")[0][0], "full")

    # ---- 7. PO budget per run + batches -------------------------------------
    def test_7_po_budget_stops_the_run_and_next_runs_continue(self):
        f = self.fake
        for i in range(10):                                    # 10 POs of one supplier, distinct times
            f.pos[f"B{i:02d}"] = po(f"B{i:02d}", "S1", ago(250 - i))
            f.items.append(item(f"B{i:02d}"))
        total = 3 + 10
        counts = []
        for _ in range(8):
            self.run_app(po_top=4, po_batch=2)
            counts.append(self.count("purchase_order"))
            if counts[-1] == total:
                break
        self.assertEqual(counts[-1], total, f"all POs must arrive eventually, progress: {counts}")
        self.assertGreater(len(counts), 1, "a budget of 4 POs per run cannot finish 13 POs in one run")
        self.assertTrue(all(b >= a for a, b in zip(counts, counts[1:])))
        self.assertIn("committed batch", self.out)

    # ---- 8. many POs with the SAME timestamp ---------------------------------
    def test_8_identical_timestamps_do_not_stall_paging(self):
        f = self.fake
        same = ago(50)
        for i in range(9):                                     # 9 POs share ONE timestamp, batch = 2
            f.pos[f"T{i}"] = po(f"T{i}", "S1", same)
            f.items.append(item(f"T{i}"))
        total = 3 + 9
        for run_no in range(1, 12):
            self.run_app(po_top=4, po_batch=2)
            if self.count("purchase_order") == total:
                break
        self.assertEqual(self.count("purchase_order"), total,
                         "keyset paging must get past POs that share the same timestamp")
        self.assertLess(run_no, 11)

    # ---- 9. quota between two batches ------------------------------------------
    def test_9_quota_between_batches_keeps_finished_batches(self):
        f = self.fake
        for i in range(6):
            f.pos[f"Q{i}"] = po(f"Q{i}", "S1", ago(250 - i))
            f.items.append(item(f"Q{i}"))
        f.quota_after_po_calls = 1                              # 1st PO batch ok, 2nd raises
        with self.assertRaises(SAPQuotaExceeded):
            self.run_app(po_batch=3)
        self.assertEqual(self.last_run()[1], "QUOTA")
        done = self.count("purchase_order")
        self.assertGreater(done, 0, "the batch finished before the quota error must be committed")
        self.assertLess(done, 3 + 6)
        self.assertIsNotNone(self.cursor_of("S1"))

        f.quota_after_po_calls = None
        self.run_app(po_batch=3)
        self.assertEqual(self.last_run()[1], "OK")
        self.assertEqual(self.count("purchase_order"), 3 + 6, "nothing lost, nothing duplicated")

    # ---- 10. suppliers sharing one date, small SUPPLIER_TOP -----------------------
    def test_10_suppliers_with_identical_date_page_forward(self):
        f = self.fake
        f.suppliers.clear(); f.pos.clear(); f.items.clear(); f.refs.clear(); f.invoices.clear()
        same = ago(60)
        for i in range(7):
            f.suppliers[f"X{i}"] = sup(f"X{i}", f"Name{i}", same)
        for run_no in range(1, 10):
            self.run_app(supplier_top=3)
            if self.count("supplier") == 7:
                break
        self.assertEqual(self.count("supplier"), 7, "keyset (date, Supplier) must page past equal dates")
        self.assertLessEqual(run_no, 4)

    # ---- 11. cursors that outlive their data are discarded -----------------------
    def test_11_cursors_are_reset_when_the_data_tables_were_emptied(self):
        self.run_app()
        self.assertEqual(self.count("purchase_order"), 3)
        conn = _connect()
        with conn.cursor() as cur:   # someone wipes the data but not the bookkeeping
            cur.execute("TRUNCATE invoice_po_reference, supplier_invoice, purchase_order_item, "
                        "purchase_order, supplier_text, supplier_purchasing_org, supplier_company, supplier CASCADE")
        conn.commit(); conn.close()
        self.run_app()
        self.assertIn("reset", self.out)
        self.assertEqual((self.count("supplier"), self.count("purchase_order")), (3, 3),
                         "after the reset everything is fetched again")


if __name__ == "__main__":
    unittest.main()
