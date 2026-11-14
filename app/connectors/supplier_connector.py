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

from datetime import datetime

import requests

from app.odata import (
    entry_properties,
    inline_nav_properties,
    iter_v2_entries,
    parse_feed,
    keyset_filter,
    watermark_filter,
)
from app.sap_client import SAPClient, SAPQuotaExceeded

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


def _fetch_with_expand(client: SAPClient, top: int, page_size: int, extra: dict) -> dict:
    result: dict = {"suppliers": [], **{v: [] for v in NAV_TARGETS.values()},
                    "_ordered": "$orderby" in extra}

    params = {"$expand": ",".join(NAV_TARGETS), **extra}  # the server must support $expand for this to work

    try:
        for entry in iter_v2_entries(client, SUPPLIER_PATH, params, page_size, top):
            props = entry_properties(entry)
            sid = props.get("Supplier", "")
            if not sid:
                continue

            # Collect the children first and add supplier + children together,
            # so a quota error never leaves a supplier with half its children.
            children: dict[str, list] = {}
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
                children[key] = rows
            result["suppliers"].append(props)
            for key, rows in children.items():
                result[key].extend(rows)
    except SAPQuotaExceeded as exc:
        exc.partial = result  # everything fetched before the quota ran out
        raise
    return result


def _fetch_per_supplier(client: SAPClient, top: int, page_size: int, extra: dict) -> dict:
    result: dict = {"suppliers": [], **{v: [] for v in NAV_TARGETS.values()},
                    "_ordered": "$orderby" in extra}
    try:
        for entry in iter_v2_entries(client, SUPPLIER_PATH, extra or None, page_size, top):
            props = entry_properties(entry)
            sid = props.get("Supplier", "")
            if not sid:
                continue
            children: dict[str, list] = {}
            for nav, key in NAV_TARGETS.items():
                try:
                    rows = fetch_supplier_related(client, sid, nav)
                except requests.HTTPError as exc:
                    print(f"  [WARN] Could not fetch {nav} for supplier {sid}: {exc}")
                    continue
                for row in rows:
                    row.setdefault("Supplier", sid)
                children[key] = rows
            result["suppliers"].append(props)
            for key, rows in children.items():
                result[key].extend(rows)
    except SAPQuotaExceeded as exc:
        exc.partial = result
        raise
    return result


def _fetch(client: SAPClient, top: int, page_size: int, use_expand: bool, extra: dict) -> dict:
    if use_expand:
        try:
            return _fetch_with_expand(client, top, page_size, extra)
        except requests.HTTPError as exc:
            if extra:
                raise  # probably the date filter, not $expand - the caller drops the filter
            print(f"  [WARN] $expand request failed ({exc}); "
                  f"falling back to one call per supplier (slow, uses more quota).")
    return _fetch_per_supplier(client, top, page_size, extra)


def fetch_all_suppliers_with_related(
    client: SAPClient,
    top: int = 800,
    page_size: int = 50,
    use_expand: bool = True,
    watermark: datetime | None = None,
    date_field: str = "CreationDate",
    date_type: str = "date",
    ordered: bool = False,
    watermark_key: str | None = None,
) -> dict:
    """Return a dict with keys 'suppliers', 'companies', 'purch_orgs', 'texts'.

    Each value is a list of raw property dicts ready to be mapped.  The extra
    key ``'_ordered'`` says whether the rows came back oldest-first (see below).

    Incremental mode
    ----------------
    * ``watermark`` given -> only suppliers with ``date_field >= watermark``;
      with ``watermark_key`` too, only suppliers strictly *after* the row
      ``(watermark, watermark_key)`` (so ties on the date cannot stall paging).
    * ``ordered=True`` or a watermark -> ``$orderby date_field asc, Supplier asc``.

    Oldest-first matters: if ``top`` cuts the list short, the highest value
    that *was* fetched is a safe new watermark and the next run continues
    where this one stopped.  ``Supplier`` is the tie-breaker so ``$skip`` paging
    is stable when many suppliers share the same date.  If SAP rejects the
    filter or the ordering, a warning is printed and everything is fetched
    unordered instead (``'_ordered'`` is then False and no watermark is kept).

    ``SAPQuotaExceeded`` is deliberately NOT caught here - it must stop the run
    (the partial result fetched so far is attached as ``exc.partial``).
    """
    if watermark is not None or ordered:
        extra = {"$orderby": f"{date_field} asc, Supplier asc"}
        if watermark is not None:
            extra["$filter"] = keyset_filter(date_field, date_type, watermark, 2,
                                             "Supplier", watermark_key)
        try:
            return _fetch(client, top, page_size, use_expand, extra)
        except requests.HTTPError as exc:
            print(f"  [WARN] SAP rejected the supplier date filter/ordering on '{date_field}' ({exc}); "
                  f"falling back to a plain full fetch (no incremental saving for suppliers).")
    return _fetch(client, top, page_size, use_expand, {})
