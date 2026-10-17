"""
Purchase order connector — fetches PO headers and their line items
from the SAP Purchase Order API (OData V4 / JSON).
"""

from app.sap_client import SAPClient

PO_BASE = (
    "/sap/opu/odata4/sap/api_purchaseorder_2"
    "/srvd_a2x/sap/purchaseorder/0001"
)
PO_PATH = f"{PO_BASE}/PurchaseOrder"
PO_ITEM_PATH = f"{PO_BASE}/PurchaseOrderItem"


def fetch_purchase_orders(
    client: SAPClient,
    supplier_id: str,
    top: int = 5000,
) -> list[dict]:
    """Fetch PO headers for a given supplier (OData V4 JSON)."""
    params = {
        "$top": str(top),
        "$filter": f"Supplier eq '{supplier_id}'",
    }
    data = client.get_json(PO_PATH, params=params)
    return data.get("value", [])


def fetch_purchase_order_items(
    client: SAPClient,
    purchase_order: str,
    top: int = 5000,
) -> list[dict]:
    """Fetch line items for a specific purchase order.

    Tries the dedicated PurchaseOrderItem entity set with a filter
    on PurchaseOrder.
    """
    params = {
        "$top": str(top),
        "$filter": f"PurchaseOrder eq '{purchase_order}'",
    }
    data = client.get_json(PO_ITEM_PATH, params=params)
    return data.get("value", [])


def fetch_all_pos_with_items(
    client: SAPClient,
    supplier_ids: list[str],
    top: int = 5000,
) -> dict:
    """Return {'orders': [...], 'items': [...]} for all given suppliers."""
    orders: list[dict] = []
    items: list[dict] = []

    for sid in supplier_ids:
        try:
            pos = fetch_purchase_orders(client, sid, top)
        except Exception as exc:
            print(f"  [WARN] Could not fetch POs for supplier {sid}: {exc}")
            continue

        orders.extend(pos)
        for po in pos:
            po_num = po.get("PurchaseOrder", "")
            if not po_num:
                continue
            try:
                po_items = fetch_purchase_order_items(client, po_num, top)
                items.extend(po_items)
            except Exception as exc:
                print(f"  [WARN] Could not fetch items for PO {po_num}: {exc}")

    return {"orders": orders, "items": items}
