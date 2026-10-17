"""
Invoice connector — fetches supplier invoice headers and
invoice-to-PO-item references from the SAP Supplier Invoice
Process API (OData V2 / XML-Atom).

NOTE on invoice headers
-----------------------
The documented sample resource is ``A_SuplrInvcItemPurOrdRef``, which
returns *invoice item–to–PO references*, not full invoice headers.

For invoice headers we use the ``A_SupplierInvoice`` resource from the
same service group ``API_SUPPLIERINVOICE_PROCESS_SRV``.  If this
resource is not accessible in a given SAP system, the connector will
skip invoice-header extraction and report the gap.
"""

import xml.etree.ElementTree as ET
from typing import Any

from app.sap_client import SAPClient

# OData V2 namespaces (same as supplier connector)
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
    "d": "http://schemas.microsoft.com/ado/2007/08/dataservices",
}

INVOICE_SRV = "/sap/opu/odata/sap/API_SUPPLIERINVOICE_PROCESS_SRV"
INV_HEADER_PATH = f"{INVOICE_SRV}/A_SupplierInvoice"
INV_PO_REF_PATH = f"{INVOICE_SRV}/A_SuplrInvcItemPurOrdRef"


def _parse_properties(entry_el: ET.Element) -> dict[str, Any]:
    """Extract <d:*> property elements from an OData V2 <entry>."""
    props: dict[str, Any] = {}
    content = entry_el.find("atom:content", NS)
    if content is None:
        return props
    m_props = content.find("m:properties", NS)
    if m_props is None:
        return props
    for child in m_props:
        tag = child.tag.split("}")[-1]
        if child.attrib.get(f"{{{NS['m']}}}null") == "true":
            props[tag] = None
        else:
            props[tag] = child.text or ""
    return props


def _parse_feed(xml_text: str) -> list[dict[str, Any]]:
    """Parse an OData V2 Atom feed into a list of property dicts."""
    root = ET.fromstring(xml_text)
    entries = root.findall("atom:entry", NS)
    if not entries:
        entries = [root] if root.tag.endswith("entry") else []
    return [_parse_properties(e) for e in entries]


# ------------------------------------------------------------------
# Invoice-to-PO references (A_SuplrInvcItemPurOrdRef)
# ------------------------------------------------------------------

def fetch_invoice_po_refs_for_po(
    client: SAPClient,
    purchase_order: str,
    top: int = 5000,
) -> list[dict]:
    """Fetch invoice-to-PO-item reference records filtered by PO number."""
    params = {
        "$top": str(top),
        "$filter": f"PurchaseOrder eq '{purchase_order}'",
    }
    xml_text = client.get_xml(INV_PO_REF_PATH, params=params)
    return _parse_feed(xml_text)


# ------------------------------------------------------------------
# Invoice headers (A_SupplierInvoice)
# ------------------------------------------------------------------

def fetch_invoice_header(
    client: SAPClient,
    supplier_invoice: str,
    fiscal_year: str,
) -> dict | None:
    """Fetch a single invoice header by its composite key."""
    path = (
        f"{INV_HEADER_PATH}"
        f"(SupplierInvoice='{supplier_invoice}',FiscalYear='{fiscal_year}')"
    )
    try:
        xml_text = client.get_xml(path)
        entries = _parse_feed(xml_text)
        return entries[0] if entries else None
    except Exception as exc:
        print(f"  [WARN] Could not fetch invoice header {supplier_invoice}/{fiscal_year}: {exc}")
        return None


# ------------------------------------------------------------------
# High-level orchestration
# ------------------------------------------------------------------

def fetch_all_invoices_and_refs(
    client: SAPClient,
    purchase_orders: list[str],
    top: int = 5000,
) -> dict:
    """Return {'invoice_headers': [...], 'po_refs': [...]} for the given POs.

    1. For each PO, fetch invoice-to-PO references.
    2. From those references, derive unique (SupplierInvoice, FiscalYear)
       pairs and fetch the corresponding invoice headers.
    """
    all_refs: list[dict] = []
    seen_invoice_keys: set[tuple[str, str]] = set()

    for po_num in purchase_orders:
        try:
            refs = fetch_invoice_po_refs_for_po(client, po_num, top)
            all_refs.extend(refs)
            for ref in refs:
                inv = ref.get("SupplierInvoice", "")
                fy = ref.get("FiscalYear", "")
                if inv and fy:
                    seen_invoice_keys.add((inv, fy))
        except Exception as exc:
            print(f"  [WARN] Could not fetch invoice refs for PO {po_num}: {exc}")

    # Fetch invoice headers for each unique key
    headers: list[dict] = []
    for inv_num, fy in seen_invoice_keys:
        hdr = fetch_invoice_header(client, inv_num, fy)
        if hdr:
            headers.append(hdr)

    return {"invoice_headers": headers, "po_refs": all_refs}
