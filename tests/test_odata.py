"""Tests for OData parsing, paging, $filter building and chunking."""

import unittest

from app.odata import (
    chunked, inline_nav_properties, iter_v2_entries, iter_v4_rows, entry_properties,
    or_filter, parse_entries, parse_feed, quote,
)

HEAD = ('<feed xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata" '
        'xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices">')


def entry(**props):
    inner = "".join(
        f'<d:{k} m:null="true"/>' if v is None else f"<d:{k}>{v}</d:{k}>" for k, v in props.items()
    )
    return f'<entry><content type="application/xml"><m:properties>{inner}</m:properties></content></entry>'


def feed(n_from, n_to, nxt=False):
    link = '<link rel="next" href="x"/>' if nxt else ""
    return (HEAD + link + "".join(entry(Id=str(i)) for i in range(n_from, n_to)) + "</feed>").encode()


class FakeClient:
    """Serves numbered rows honouring $top/$skip; optionally caps the server page size."""
    def __init__(self, total, server_cap=None, v4=False):
        self.total, self.cap, self.v4, self.calls = total, server_cap, v4, []

    def _slice(self, params):
        top, skip = int(params["$top"]), int(params.get("$skip", 0))
        top = min(top, self.cap) if self.cap else top
        end = min(skip + top, self.total)
        self.calls.append((top, skip))
        return skip, end, bool(self.cap and end < self.total)

    def get_xml(self, path, params=None):
        s, e, nxt = self._slice(params)
        return feed(s, e, nxt)

    def get_json(self, path, params=None):
        s, e, nxt = self._slice(params)
        data = {"value": [{"Id": str(i)} for i in range(s, e)]}
        if nxt:
            data["@odata.nextLink"] = "x"
        return data


class TestParsing(unittest.TestCase):
    def test_null_and_empty_values(self):
        props = parse_feed(HEAD + entry(A="x", B=None, C="") + "</feed>")[0]
        self.assertEqual(props, {"A": "x", "B": None, "C": ""})

    def test_non_ascii_bytes_roundtrip(self):
        xml = (HEAD + entry(Name="M\u00fcller") + "</feed>").encode("utf-8")
        self.assertEqual(parse_feed(xml)[0]["Name"], "M\u00fcller")

    def test_single_entry_document(self):
        xml = entry(A="1").replace("<entry>", '<entry xmlns="http://www.w3.org/2005/Atom" '
            'xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata" '
            'xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices">', 1)
        self.assertEqual(parse_feed(xml), [{"A": "1"}])

    def test_inline_expand(self):
        inner = HEAD + entry(Company="1710") + entry(Company="1720") + "</feed>"
        xml = (HEAD + '<entry><link title="to_X" href="h"><m:inline>' + inner
               + '</m:inline></link><content><m:properties/></content></entry></feed>')
        e, _ = parse_entries(xml)
        self.assertEqual([r["Company"] for r in inline_nav_properties(e[0], "to_X")], ["1710", "1720"])
        self.assertIsNone(inline_nav_properties(e[0], "to_missing"))


class TestPaging(unittest.TestCase):
    def test_collects_all_rows_across_pages(self):
        c = FakeClient(total=250)
        rows = [entry_properties(e)["Id"] for e in iter_v2_entries(c, "/p", page_size=100, max_records=5000)]
        self.assertEqual(len(rows), 250)
        self.assertEqual(len(c.calls), 3)  # 100 + 100 + 50(short page -> stop, no extra probe)

    def test_max_records_cap_respected(self):
        c = FakeClient(total=1000)
        rows = list(iter_v2_entries(c, "/p", page_size=100, max_records=130))
        self.assertEqual(len(rows), 130)
        self.assertEqual(c.calls[-1][0], 30)  # last request only asks for the remainder

    def test_server_side_page_cap_does_not_truncate(self):
        # server returns max 40 per page although 100 were requested; rel=next keeps us going
        c = FakeClient(total=130, server_cap=40)
        self.assertEqual(len(list(iter_v2_entries(c, "/p", page_size=100, max_records=5000))), 130)

    def test_v4_paging_and_server_cap(self):
        self.assertEqual(len(list(iter_v4_rows(FakeClient(250, v4=True), "/p", page_size=100))), 250)
        self.assertEqual(len(list(iter_v4_rows(FakeClient(130, server_cap=40), "/p", page_size=100))), 130)

    def test_exact_multiple_of_page_size_terminates(self):
        c = FakeClient(total=200)
        self.assertEqual(len(list(iter_v2_entries(c, "/p", page_size=100))), 200)
        self.assertEqual(len(c.calls), 3)  # last probe returns empty

    def test_empty_result(self):
        self.assertEqual(list(iter_v2_entries(FakeClient(0), "/p")), [])


class TestFilterHelpers(unittest.TestCase):
    def test_quote_escapes_single_quotes(self):
        self.assertEqual(quote("O'Neil"), "'O''Neil'")

    def test_or_filter(self):
        self.assertEqual(or_filter("Supplier", ["1", "2"]), "Supplier eq '1' or Supplier eq '2'")

    def test_chunked(self):
        self.assertEqual(list(chunked(range(5), 2)), [[0, 1], [2, 3], [4]])
        self.assertEqual(list(chunked([], 3)), [])


if __name__ == "__main__":
    unittest.main()
