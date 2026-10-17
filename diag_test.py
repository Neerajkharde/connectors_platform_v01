"""
Standalone diagnostic script — tests SAP sandbox endpoints one by one
to pinpoint which calls succeed and which fail (and why).

Usage:  python diag_test.py
"""

import requests
from dotenv import load_dotenv
import os

load_dotenv()

BASE = os.getenv("SAP_BASE_URL", "https://sandbox.api.sap.com/s4hanacloud")
API_KEY = os.getenv("SAP_API_KEY", "")

HEADERS = {
    "APIKey": API_KEY,
    "Accept-Encoding": "gzip, deflate",
}

SEP = "-" * 60

# Endpoints to probe (description, path, accept_header)
TESTS = [
    # 1. Supplier list  (OData V2 XML) — top-level, should always work
    (
        "Supplier list ($top=3)",
        "/sap/opu/odata/sap/API_BUSINESS_PARTNER/A_Supplier?$top=3",
        "application/atom+xml",
    ),
    # 2. Navigation link — to_SupplierCompany for supplier '1000001'
    #    (a common sandbox ID; will 404 if the ID doesn't exist)
    (
        "Supplier '1000001' → to_SupplierCompany",
        "/sap/opu/odata/sap/API_BUSINESS_PARTNER/A_Supplier('1000001')/to_SupplierCompany",
        "application/atom+xml",
    ),
    # 3. Navigation link — to_SupplierPurchasingOrg
    (
        "Supplier '1000001' → to_SupplierPurchasingOrg",
        "/sap/opu/odata/sap/API_BUSINESS_PARTNER/A_Supplier('1000001')/to_SupplierPurchasingOrg",
        "application/atom+xml",
    ),
    # 4. Navigation link — to_SupplierText
    (
        "Supplier '1000001' → to_SupplierText",
        "/sap/opu/odata/sap/API_BUSINESS_PARTNER/A_Supplier('1000001')/to_SupplierText",
        "application/atom+xml",
    ),
    # 5. Purchase orders (OData V4 JSON)
    (
        "PurchaseOrder list ($top=3)",
        "/sap/opu/odata4/sap/api_purchaseorder_2/svc/PurchaseOrder?$top=3",
        "application/json",
    ),
    # 6. Invoice PO references (OData V2 XML)
    (
        "InvoicePORef list ($top=3)",
        "/sap/opu/odata/sap/API_SUPPLIERINVOICE_PROCESS_SRV/A_SuplrInvcItemPurOrdRef?$top=3",
        "application/atom+xml",
    ),
    # 7. Supplier invoices (OData V2 XML)
    (
        "SupplierInvoice list ($top=3)",
        "/sap/opu/odata/sap/API_SUPPLIERINVOICE_PROCESS_SRV/A_SupplierInvoice?$top=3",
        "application/atom+xml",
    ),
]


def probe(desc: str, path: str, accept: str) -> None:
    url = f"{BASE}{path}"
    print(f"\n{SEP}")
    print(f"  TEST: {desc}")
    print(f"  URL : {url}")
    try:
        resp = requests.get(url, headers={**HEADERS, "Accept": accept}, timeout=30)
        print(f"  STATUS: {resp.status_code}")
        if resp.ok:
            body_preview = resp.text[:500]
            print(f"  BODY (first 500 chars):\n{body_preview}")
        else:
            print(f"  RESPONSE HEADERS: {dict(resp.headers)}")
            print(f"  ERROR BODY:\n{resp.text[:2000]}")
    except requests.exceptions.RequestException as exc:
        print(f"  EXCEPTION: {type(exc).__name__}: {exc}")
    print(SEP)


if __name__ == "__main__":
    print(f"SAP Base URL : {BASE}")
    print(f"API Key      : {API_KEY[:6]}...{API_KEY[-4:]}" if len(API_KEY) > 10 else f"API Key: {API_KEY or '(empty)'}")
    print(f"Running {len(TESTS)} endpoint probes...\n")

    for desc, path, accept in TESTS:
        probe(desc, path, accept)

    print("\n✅ Diagnostic run complete.")
