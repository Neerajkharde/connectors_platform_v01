"""
Purchase order connector — fetches PO headers and their line items
from the SAP Purchase Order API (OData V4 / JSON).

Call-count strategy
-------------------
Instead of one request per supplier and one per PO, the keys are combined
into OR-filters (``Supplier eq 'a' or Supplier eq 'b' ...``) of
``chunk_size`` keys per request, and every request is paged.
"""

import requests

from app.odata import chunked, iter_v4_rows, or_filter
from app.sap_client import SAPClient

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
) -> list[dict]:
    """Fetch PO headers for a group of suppliers (OData V4 JSON)."""
    orders: list[dict] = []
    for chunk in chunked(sorted(set(supplier_ids)), chunk_size):
        if len(orders) >= top:
            break
        params = {"$filter": or_filter("Supplier", chunk)}
        try:
            orders.extend(
                iter_v4_rows(client, PO_PATH, params, page_size, top - len(orders))
            )
        except requests.HTTPError as exc:
            print(f"  [WARN] Could not fetch POs for suppliers {chunk[0]}..{chunk[-1]}: {exc}")
    return orders


def fetch_purchase_order_items(
    client: SAPClient,
    purchase_orders: list[str],
    top: int = 20000,
    page_size: int = 100,
    chunk_size: int = 20,
) -> list[dict]:
    """Fetch line items for a group of purchase orders."""
    items: list[dict] = []
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
    return items


def fetch_all_pos_with_items(
    client: SAPClient,
    supplier_ids: list[str],
    top: int = 5000,
    item_top: int = 20000,
    page_size: int = 100,
    chunk_size: int = 20,
) -> dict:
    """Return {'orders': [...], 'items': [...]} for all given suppliers."""
    orders = fetch_purchase_orders(client, supplier_ids, top, page_size, chunk_size)
    po_numbers = [po["PurchaseOrder"] for po in orders if po.get("PurchaseOrder")]
    items = fetch_purchase_order_items(client, po_numbers, item_top, page_size, chunk_size)
    return {"orders": orders, "items": items}
