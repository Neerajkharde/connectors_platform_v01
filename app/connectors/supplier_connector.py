"""
Supplier connector — fetches supplier records and their related
company, purchasing-org, and text collections from the SAP
Business Partner API (OData V2 / XML-Atom).
"""

import xml.etree.ElementTree as ET
from typing import Any

from app.sap_client import SAPClient

# OData V2 XML namespaces
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
    "d": "http://schemas.microsoft.com/ado/2007/08/dataservices",
}

SUPPLIER_PATH = "/sap/opu/odata/sap/API_BUSINESS_PARTNER/A_Supplier"


def _parse_properties(entry_el: ET.Element) -> dict[str, Any]:
    """Extract <d:*> property elements from an <entry> into a flat dict."""
    props: dict[str, Any] = {}
    content = entry_el.find("atom:content", NS)
    if content is None:
        return props
    m_props = content.find("m:properties", NS)
    if m_props is None:
        return props
    for child in m_props:
        # Tag looks like '{http://...}FieldName'
        tag = child.tag.split("}")[-1]
        # Respect m:null="true"
        if child.attrib.get(f"{{{NS['m']}}}null") == "true":
            props[tag] = None
        else:
            props[tag] = child.text or ""
    return props


def _parse_feed(xml_text: str) -> list[dict[str, Any]]:
    """Parse an OData V2 Atom feed into a list of property dicts."""
    root = ET.fromstring(xml_text)
    entries = root.findall("atom:entry", NS)
    # In case the xml_text is a single entry, not a feed
    if not entries:
        entries = [root] if root.tag.endswith("entry") else []
    return [_parse_properties(e) for e in entries]


def _get_nav_href(entry_el: ET.Element, nav_name: str) -> str | None:
    """Return the href of a navigation link, e.g. to_SupplierCompany."""
    for link in entry_el.findall("atom:link", NS):
        title = link.attrib.get("title", "")
        if title == nav_name:
            return link.attrib.get("href")
    return None


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def fetch_suppliers(client: SAPClient, top: int = 800) -> list[dict]:
    """Fetch raw supplier property dicts from the Supplier API."""
    xml_text = client.get_xml(SUPPLIER_PATH, params={"$top": str(top)})
    return _parse_feed(xml_text)


def fetch_supplier_related(
    client: SAPClient,
    supplier_id: str,
    nav_name: str,
) -> list[dict]:
    """Fetch a supplier's navigation collection (company / purch-org / text).

    Calls the navigation link endpoint, e.g.:
        A_Supplier('1018')/to_SupplierCompany
    """
    path = f"{SUPPLIER_PATH}('{supplier_id}')/{nav_name}"
    xml_text = client.get_xml(path)
    return _parse_feed(xml_text)


def fetch_all_suppliers_with_related(
    client: SAPClient, top: int = 800
) -> dict:
    """Return a dict with keys 'suppliers', 'companies', 'purch_orgs', 'texts'.

    Each value is a list of raw property dicts ready to be mapped.
    """
    suppliers = fetch_suppliers(client, top)
    companies: list[dict] = []
    purch_orgs: list[dict] = []
    texts: list[dict] = []

    for sup_props in suppliers:
        sid = sup_props.get("Supplier", "")
        if not sid:
            continue
        try:
            companies.extend(fetch_supplier_related(client, sid, "to_SupplierCompany"))
        except Exception as exc:
            print(f"  [WARN] Could not fetch companies for supplier {sid}: {exc}")
        try:
            purch_orgs.extend(fetch_supplier_related(client, sid, "to_SupplierPurchasingOrg"))
        except Exception as exc:
            print(f"  [WARN] Could not fetch purch-orgs for supplier {sid}: {exc}")
        try:
            texts.extend(fetch_supplier_related(client, sid, "to_SupplierText"))
        except Exception as exc:
            print(f"  [WARN] Could not fetch texts for supplier {sid}: {exc}")

    return {
        "suppliers": suppliers,
        "companies": companies,
        "purch_orgs": purch_orgs,
        "texts": texts,
    }
