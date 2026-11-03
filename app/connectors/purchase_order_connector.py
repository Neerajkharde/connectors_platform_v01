"""
Purchase order connector — fetches PO headers and their line items
from the SAP Purchase Order API (OData V4 / JSON).

Call-count strategy
-------------------
Instead of one request per supplier and one per PO, the keys are combined
into OR-filters (``Supplier eq 'a' or Supplier eq 'b' ...``) of
``chunk_size`` keys per request, and every request is paged.
"""

from datetime import datetime

import requests

from app.odata import and_filter, chunked, iter_v4_rows, keyset_filter, or_filter, watermark_filter
from app.sap_client import SAPClient, SAPQuotaExceeded

PO_BASE = (
    "/sap/opu/odata4/sap/api_purchaseorder_2"
    "/srvd_a2x/sap/purchaseorder/0001"
)
PO_PATH = f"{PO_BASE}/PurchaseOrder"
PO_ITEM_PATH = f"{PO_BASE}/PurchaseOrderItem"


def fetch_purchase_orders(
    client: SAPClient,
    supplier_ids: list[str],
    top: int = 5000,
    page_size: int = 100,
    chunk_size: int = 20,
    watermark: datetime | None = None,
    date_field: str = "LastChangeDateTime",
    date_type: str = "datetimeoffset",
    stats: dict | None = None,
) -> list[dict]:
    """Fetch PO headers for a group of suppliers (OData V4 JSON).

    Incremental mode: with ``watermark`` only POs with ``date_field >= watermark``
    are requested.  If SAP rejects the filter, the connector warns and fetches
    all POs of the chunk instead (and keeps doing so for the rest of the run).

    ``stats`` (optional out-parameter) is filled with:
      * ``complete``       - True if every supplier chunk was processed to the end
                             (False when ``top`` cut the run short).  Only a
                             complete run may move the PO watermark forward,
                             because each chunk is sorted on its own.
      * ``filter_dropped`` - True if the date filter had to be abandoned.
    """
    orders: list[dict] = []
    use_wm = watermark is not None
    filter_dropped = False
    complete = True

    try:
        for chunk in chunked(sorted(set(supplier_ids)), chunk_size):
            if len(orders) >= top:
                complete = False
                break
            while True:
                base = or_filter("Supplier", chunk)
                if use_wm:
                    flt = and_filter(base, watermark_filter(date_field, date_type, watermark, odata_version=4))
                    params = {"$filter": flt, "$orderby": f"{date_field} asc, PurchaseOrder asc"}
                else:
                    params = {"$filter": base}
                try:
                    orders.extend(
                        iter_v4_rows(client, PO_PATH, params, page_size, top - len(orders))
                    )
                    if len(orders) >= top:
                        complete = False  # the cap may have cut this chunk short
                except requests.HTTPError as exc:
                    if use_wm:
                        print(f"  [WARN] SAP rejected the PO date filter on '{date_field}' ({exc}); "
                              f"falling back to a full fetch (no incremental saving for POs).")
                        use_wm, filter_dropped = False, True
                        continue  # retry this chunk without the filter
                    print(f"  [WARN] Could not fetch POs for suppliers {chunk[0]}..{chunk[-1]}: {exc}")
                    complete = False  # a chunk is missing -> do not trust the watermark
                break
    except SAPQuotaExceeded as exc:
        exc.partial = orders
        raise
    finally:
        if stats is not None:
            stats["complete"] = complete
            stats["filter_dropped"] = filter_dropped
    return orders


def fetch_po_batch(
    client: SAPClient,
    supplier_ids: list[str],
    cursor: tuple | None,
    batch: int,
    page_size: int = 100,
    date_field: str = "LastChangeDateTime",
    date_type: str = "datetimeoffset",
) -> list[dict]:
    """The next ``batch`` POs of ``supplier_ids`` after ``cursor`` (resumable paging).

    Rows come back oldest first in ``(date_field, PurchaseOrder)`` order and
    only those strictly after ``cursor = (value, key)`` (or from the very start
    when ``cursor`` is None).  Because the order is total, the last row returned
    is a safe cursor for *all* the given suppliers - even if thousands of POs
    share one timestamp.

    ``requests.HTTPError`` is NOT caught: it usually means SAP does not support
    the date field in $filter/$orderby, and the caller falls back.
    """
    flt = or_filter("Supplier", supplier_ids)
    if cursor is not None:
        value, key = cursor
        flt = and_filter(flt, keyset_filter(date_field, date_type, value, 4, "PurchaseOrder", key))
    params = {"$filter": flt, "$orderby": f"{date_field} asc, PurchaseOrder asc"}
    return list(iter_v4_rows(client, PO_PATH, params, page_size, batch))


def fetch_purchase_order_items(
    client: SAPClient,
    purchase_orders: list[str],
    top: int = 20000,
    page_size: int = 100,
    chunk_size: int = 20,
) -> list[dict]:
    """Fetch line items for a group of purchase orders."""
    items: list[dict] = []
    try:
        for chunk in chunked(sorted(set(purchase_orders)), chunk_size):
            if len(items) >= top:
                break
            params = {"$filter": or_filter("PurchaseOrder", chunk)}
            try:
                items.extend(
                    iter_v4_rows(client, PO_ITEM_PATH, params, page_size, top - len(items))
                )
            except requests.HTTPError as exc:
                print(f"  [WARN] Could not fetch items for POs {chunk[0]}..{chunk[-1]}: {exc}")
    except SAPQuotaExceeded as exc:
        exc.partial = items
        raise
    return items


def fetch_all_pos_with_items(
    client: SAPClient,
    supplier_ids: list[str],
    top: int = 5000,
    item_top: int = 20000,
    page_size: int = 100,
    chunk_size: int = 20,
    watermark: datetime | None = None,
    date_field: str = "LastChangeDateTime",
    date_type: str = "datetimeoffset",
) -> dict:
    """Return {'orders': [...], 'items': [...], 'complete': bool, 'filter_dropped': bool}.

    Items are fetched for exactly the POs returned (a changed PO re-downloads
    all of its items).  On a quota error the POs/items fetched so far are
    attached to the exception as ``exc.partial``.
    """
    stats: dict = {}
    try:
        orders = fetch_purchase_orders(
            client, supplier_ids, top, page_size, chunk_size,
            watermark=watermark, date_field=date_field, date_type=date_type, stats=stats,
        )
    except SAPQuotaExceeded as exc:
        exc.partial = {"orders": exc.partial, "items": [], **stats}
        raise
    po_numbers = [po["PurchaseOrder"] for po in orders if po.get("PurchaseOrder")]
    try:
        items = fetch_purchase_order_items(client, po_numbers, item_top, page_size, chunk_size)
    except SAPQuotaExceeded as exc:
        exc.partial = {"orders": orders, "items": exc.partial, **stats, "complete": False}
        raise
    return {"orders": orders, "items": items, **stats}
