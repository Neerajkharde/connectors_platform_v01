"""
Standalone diagnostic - probes the SAP endpoints one by one (1 call each) to show
which succeed and why one fails.

Usage:   python diag_test.py
Safe to redirect:   python diag_test.py > diag_output.txt 2>&1

* Output is plain ASCII/UTF-8-safe (the old version crashed on Windows when
  redirected, because '->' was written as a unicode arrow).
* Stops at the first QUOTA error - further calls cannot succeed and only waste quota.
* Uses the same endpoint paths as the real connectors (the old PO path was wrong).
* Never prints the API key.
"""

import os
import re
import sys

import requests
from dotenv import load_dotenv

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from app.connectors.invoice_connector import INV_HEADER_PATH, INV_PO_REF_PATH
from app.connectors.purchase_order_connector import PO_PATH, PO_ITEM_PATH
from app.connectors.supplier_connector import SUPPLIER_PATH

load_dotenv()
BASE = os.getenv("SAP_BASE_URL", "https://sandbox.api.sap.com/s4hanacloud").rstrip("/")
API_KEY = os.getenv("SAP_API_KEY", "")
SEP = "-" * 60
XML, JSON = "application/atom+xml", "application/json"


def probe(desc: str, path: str, accept: str) -> tuple[str, str]:
    """Return (outcome, body) where outcome is 'ok', 'quota' or 'error'."""
    url = f"{BASE}{path}"
    print(f"\n{SEP}\n  TEST  : {desc}\n  URL   : {url}")
    try:
        resp = requests.get(url, headers={"APIKey": API_KEY, "Accept": accept}, timeout=30)
    except requests.exceptions.RequestException as exc:
        print(f"  RESULT: EXCEPTION {type(exc).__name__}: {exc}")
        return "error", ""
    print(f"  STATUS: {resp.status_code}")
    if resp.ok:
        print(f"  BODY (first 300 chars): {resp.text[:300]!r}")
        return "ok", resp.text
    body = resp.text[:600]
    if API_KEY:  # SAP's quota error echoes the API key in its message
        body = body.replace(API_KEY, "***redacted***")
    print(f"  ERROR BODY: {body}")
    if "QuotaViolation" in body:
        return "quota", body
    return "error", body


def main() -> None:
    masked = f"{API_KEY[:4]}...{API_KEY[-2:]}" if len(API_KEY) > 10 else ("(empty)" if not API_KEY else "(short)")
    print(f"SAP Base URL : {BASE}\nAPI Key      : {masked}")

    # (description, path, accept) - supplier navigation probes use a real supplier id from probe 1
    probes = [("Supplier list ($top=1)", f"{SUPPLIER_PATH}?$top=1", XML)]
    plan_after_supplier = [
        ("Supplier -> to_SupplierCompany", "{sup}/to_SupplierCompany", XML),
        ("Supplier -> to_SupplierPurchasingOrg", "{sup}/to_SupplierPurchasingOrg", XML),
        ("Supplier -> to_SupplierText", "{sup}/to_SupplierText", XML),
        ("Supplier list with $expand (what the connector uses)",
         f"{SUPPLIER_PATH}?$top=1&$expand=to_SupplierCompany,to_SupplierPurchasingOrg,to_SupplierText", XML),
    ]
    fixed = [
        ("PurchaseOrder list ($top=1)", f"{PO_PATH}?$top=1", JSON),
        ("PurchaseOrderItem list ($top=1)", f"{PO_ITEM_PATH}?$top=1", JSON),
        ("Invoice PO references ($top=1)", f"{INV_PO_REF_PATH}?$top=1", XML),
        ("Supplier invoices ($top=1)", f"{INV_HEADER_PATH}?$top=1", XML),
    ]

    results = []
    outcome, body = probe(*probes[0])
    results.append((probes[0][0], outcome))

    todo = []
    if outcome == "ok":
        m = re.search(r"<d:Supplier>([^<]+)</d:Supplier>", body)
        sup = f"{SUPPLIER_PATH}('{m.group(1)}')" if m else None
        todo += [(d, p.format(sup=sup), a) for d, p, a in plan_after_supplier[:3]] if sup else []
        todo.append(plan_after_supplier[3])
    todo += fixed

    if outcome != "quota":
        for desc, path, accept in todo:
            outcome, _ = probe(desc, path, accept)
            results.append((desc, outcome))
            if outcome == "quota":
                break

    print(f"\n{SEP}\nSUMMARY")
    for desc, res in results:
        print(f"  [{res.upper():5}] {desc}")
    if any(r == "quota" for _, r in results):
        print("\nThe API key's quota is exhausted (policies.ratelimit.QuotaViolation).\n"
              "This is a server-side limit, not a bug in the connector: wait for the quota\n"
              "to reset or use another key. Remaining probes were skipped to save quota.")
    print("\nDiagnostic run complete.")


if __name__ == "__main__":
    main()
