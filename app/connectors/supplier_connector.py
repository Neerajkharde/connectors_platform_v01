"""
Supplier connector — fetches supplier records and their related
company, purchasing-org, and text collections from the SAP
Business Partner API (OData V2 / XML-Atom).

Call-count strategy
-------------------
The original code made 1 + 3 x <suppliers> calls (2,401 for 800 suppliers).
Now the three sub-collections are delivered *inside* the supplier pages via
``$expand`` -> roughly <suppliers> / <page_size> calls.  If the server rejects
``$expand`` the connector falls back to the per-supplier navigation calls.
"""

import requests

from app.odata import (
    entry_properties,
    inline_nav_properties,
    iter_v2_entries,
    parse_feed,
)
from app.sap_client import SAPClient

SUPPLIER_PATH = "/sap/opu/odata/sap/API_BUSINESS_PARTNER/A_Supplier"

# navigation property -> key in the result dict
NAV_TARGETS = {
    "to_SupplierCompany": "companies",
    "to_SupplierPurchasingOrg": "purch_orgs",
    "to_SupplierText": "texts",
}


def fetch_supplier_related(client: SAPClient, supplier_id: str, nav_name: str) -> list[dict]:
    """Fetch one navigation collection of one supplier (1 HTTP call).

    Only used as a fallback when ``$expand`` is not available.
    """
    path = f"{SUPPLIER_PATH}('{supplier_id}')/{nav_name}"
    return parse_feed(client.get_xml(path))


def _fetch_with_expand(client: SAPClient, top: int, page_size: int) -> dict:
    result: dict = {"suppliers": [], **{v: [] for v in NAV_TARGETS.values()}}

    params = {"$expand": ",".join(NAV_TARGETS)} # Important: the server must support these navigation properties and $expand for this to work.

    for entry in iter_v2_entries(client, SUPPLIER_PATH, params, page_size, top):
        props = entry_properties(entry)
        sid = props.get("Supplier", "")
        if not sid:
            continue

        result["suppliers"].append(props)
        
        for nav, key in NAV_TARGETS.items():
            rows = inline_nav_properties(entry, nav)
            if rows is None:  # server ignored $expand for this entry
                try:
                    rows = fetch_supplier_related(client, sid, nav)
                except requests.HTTPError as exc:
                    print(f"  [WARN] Could not fetch {nav} for supplier {sid}: {exc}")
                    rows = []
            for row in rows:
                row.setdefault("Supplier", sid)  # child rows always know their parent
                result[key].append(row)
    return result


def _fetch_per_supplier(client: SAPClient, top: int, page_size: int) -> dict:
    result: dict = {"suppliers": [], **{v: [] for v in NAV_TARGETS.values()}}
    for entry in iter_v2_entries(client, SUPPLIER_PATH, None, page_size, top):
        props = entry_properties(entry)
        sid = props.get("Supplier", "")
        if not sid:
            continue
        result["suppliers"].append(props)
        for nav, key in NAV_TARGETS.items():
            try:
                rows = fetch_supplier_related(client, sid, nav)
            except requests.HTTPError as exc:
                print(f"  [WARN] Could not fetch {nav} for supplier {sid}: {exc}")
                continue
            for row in rows:
                row.setdefault("Supplier", sid)
                result[key].append(row)
    return result


def fetch_all_suppliers_with_related(
    client: SAPClient,
    top: int = 800,
    page_size: int = 50,
    use_expand: bool = True,
) -> dict:
    """Return a dict with keys 'suppliers', 'companies', 'purch_orgs', 'texts'.

    Each value is a list of raw property dicts ready to be mapped.
    ``SAPQuotaExceeded`` is deliberately NOT caught here - it must stop the run.
    """
    if use_expand:
        try:
            return _fetch_with_expand(client, top, page_size)
        except requests.HTTPError as exc:
            print(f"  [WARN] $expand request failed ({exc}); "
                  f"falling back to one call per supplier (slow, uses more quota).")
    return _fetch_per_supplier(client, top, page_size)
