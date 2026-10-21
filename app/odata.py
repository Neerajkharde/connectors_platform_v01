"""
Shared OData helpers used by all connectors.

* OData V2 (Atom/XML) parsing – including ``$expand`` inline collections
* Paging for V2 (XML) and V4 (JSON) collections
* ``$filter`` helpers – quoting and OR-chunking so that one HTTP call can
  fetch data for many keys instead of one call per key

Why this module exists
----------------------
The original connectors made one HTTP request per supplier / PO / invoice
(thousands of calls) which exhausts the SAP API Business Hub sandbox quota
almost immediately.  Everything here is about doing *fewer, bigger* calls.
"""

import xml.etree.ElementTree as ET
from typing import Any, Iterable, Iterator

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
    "d": "http://schemas.microsoft.com/ado/2007/08/dataservices",
}


# ------------------------------------------------------------------
# OData V2 / Atom parsing
# ------------------------------------------------------------------

def entry_properties(entry_el: ET.Element) -> dict[str, Any]:
    """Extract the ``<d:*>`` properties of one Atom ``<entry>`` into a dict."""
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


def parse_entries(xml_data: str | bytes) -> tuple[list[ET.Element], bool]:
    """Return ``(entry elements, has_next_link)`` for a feed or single entry."""
    root = ET.fromstring(xml_data)
    entries = root.findall("atom:entry", NS)
    if not entries and root.tag.endswith("}entry"):
        return [root], False
    has_next = any(
        link.attrib.get("rel") == "next" for link in root.findall("atom:link", NS)
    )
    return entries, has_next


def parse_feed(xml_data: str | bytes) -> list[dict[str, Any]]:
    """Parse an Atom feed (or single entry) into a list of property dicts."""
    entries, _ = parse_entries(xml_data)
    return [entry_properties(e) for e in entries]


def inline_nav_properties(entry_el: ET.Element, nav_name: str) -> list[dict] | None:
    """Rows of a navigation collection that was delivered via ``$expand``.

    Returns ``None`` when the entry carries no inline data for ``nav_name``
    (so the caller can fall back to a separate request), and ``[]`` when the
    collection was expanded but is simply empty.
    """
    for link in entry_el.findall("atom:link", NS):
        if link.attrib.get("title") != nav_name:
            continue
        inline = link.find("m:inline", NS)
        if inline is None:
            return None
        feed = inline.find("atom:feed", NS)
        if feed is None:
            entry = inline.find("atom:entry", NS)  # 0..1 navigation
            return [entry_properties(entry)] if entry is not None else []
        return [entry_properties(e) for e in feed.findall("atom:entry", NS)]
    return None


# ------------------------------------------------------------------
# Paging
# ------------------------------------------------------------------

def iter_v2_entries(
    client,
    path: str,
    params: dict | None = None,
    page_size: int = 100,
    max_records: int = 5000,
) -> Iterator[ET.Element]:
    """Yield Atom ``<entry>`` elements page by page using ``$top``/``$skip``.

    Stops after ``max_records`` entries, when a short page is returned, or
    when an empty page is returned.  A server-side ``rel="next"`` link keeps
    paging going even if the server caps the page below ``page_size``.
    """
    skip = 0
    while skip < max_records:
        want = min(page_size, max_records - skip)
        page_params = dict(params or {})
        page_params["$top"] = str(want)
        if skip:
            page_params["$skip"] = str(skip)
        entries, has_next = parse_entries(client.get_xml(path, params=page_params))
        for entry in entries:
            yield entry
        skip += len(entries)
        if not entries or (len(entries) < want and not has_next):
            return


def iter_v4_rows(
    client,
    path: str,
    params: dict | None = None,
    page_size: int = 100,
    max_records: int = 5000,
) -> Iterator[dict]:
    """Yield JSON rows of an OData V4 collection page by page."""
    skip = 0
    while skip < max_records:
        want = min(page_size, max_records - skip)
        page_params = dict(params or {})
        page_params["$top"] = str(want)
        if skip:
            page_params["$skip"] = str(skip)
        data = client.get_json(path, params=page_params)
        rows = data.get("value", [])
        for row in rows:
            yield row
        skip += len(rows)
        has_next = "@odata.nextLink" in data
        if not rows or (len(rows) < want and not has_next):
            return


# ------------------------------------------------------------------
# $filter helpers
# ------------------------------------------------------------------

def quote(value: str) -> str:
    """OData string literal – single quotes are escaped by doubling."""
    return "'" + str(value).replace("'", "''") + "'"


def chunked(items: Iterable, size: int) -> Iterator[list]:
    """Yield lists of at most ``size`` items."""
    batch: list = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def or_filter(field: str, values: Iterable[str]) -> str:
    """``Field eq 'a' or Field eq 'b' ...`` – one request for many keys."""
    return " or ".join(f"{field} eq {quote(v)}" for v in values)
