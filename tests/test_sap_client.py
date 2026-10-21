"""Tests for the SAP client: quota fail-fast, retry, throttle, redaction."""

import unittest
from unittest.mock import MagicMock

import requests

from app.config import SAPConfig
from app.sap_client import SAPClient, SAPQuotaExceeded

QUOTA_BODY = (
    '{"fault":{"faultstring":"Rate limit quota violation. Quota limit  exceeded. '
    'Identifier : SECRETKEY123","detail":{"errorcode":"policies.ratelimit.QuotaViolation"}}}'
)
SPIKE_BODY = '{"fault":{"faultstring":"Spike arrest","detail":{"errorcode":"policies.ratelimit.SpikeArrestViolation"}}}'


def make_config(**kw) -> SAPConfig:
    base = dict(base_url="http://sap.test", api_key="SECRETKEY123", username="", password="",
                auth_mode="apikey", supplier_top=10, po_top=10, invoice_top=10,
                request_delay=0.0, max_retries=2)
    base.update(kw)
    return SAPConfig(**base)


def resp(status=200, body="<x/>", headers=None):
    r = requests.Response()
    r.status_code = status
    r._content = body.encode("utf-8")
    r.headers.update(headers or {})
    r.request = requests.Request("GET", "http://sap.test/x", headers={"APIKey": "SECRETKEY123"}).prepare()
    r.url = "http://sap.test/x"
    return r


def client_with(responses, **cfg):
    sleeps = []
    c = SAPClient(make_config(**cfg), sleep=sleeps.append)
    c.session.get = MagicMock(side_effect=responses)
    return c, sleeps


class TestQuota(unittest.TestCase):
    def test_quota_error_raises_and_blocks_further_calls(self):
        c, sleeps = client_with([resp(500, QUOTA_BODY)])
        with self.assertRaises(SAPQuotaExceeded):
            c.get_xml("/a")
        self.assertEqual(c.session.get.call_count, 1)
        # every later call must fail WITHOUT touching the network
        with self.assertRaises(SAPQuotaExceeded):
            c.get_xml("/b")
        with self.assertRaises(SAPQuotaExceeded):
            c.get_json("/c")
        self.assertEqual(c.session.get.call_count, 1)
        self.assertEqual(sleeps, [])  # quota errors are never retried

    def test_diagnostics_never_print_the_api_key(self):
        c, _ = client_with([resp(500, QUOTA_BODY)])  # body echoes the key, exactly like real SAP
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SAPQuotaExceeded):
            c.get_xml("/a")
        self.assertNotIn("SECRETKEY123", buf.getvalue())
        self.assertIn("redacted", buf.getvalue())
        self.assertIn("QuotaViolation", buf.getvalue())  # still useful for debugging


class TestRetry(unittest.TestCase):
    def test_spike_arrest_is_retried_then_succeeds(self):
        c, sleeps = client_with([resp(500, SPIKE_BODY), resp(429), resp(200, "<ok/>")])
        self.assertEqual(c.get_xml("/a"), b"<ok/>")
        self.assertEqual(c.session.get.call_count, 3)
        self.assertEqual(len(sleeps), 2)

    def test_retry_after_header_is_honoured(self):
        c, sleeps = client_with([resp(429, headers={"Retry-After": "7"}), resp(200)])
        c.get_xml("/a")
        self.assertEqual(sleeps, [7.0])

    def test_gives_up_after_max_retries(self):
        c, _ = client_with([resp(503)] * 5, max_retries=2)
        with self.assertRaises(requests.HTTPError):
            c.get_xml("/a")
        self.assertEqual(c.session.get.call_count, 3)  # 1 try + 2 retries

    def test_404_is_not_retried(self):
        c, sleeps = client_with([resp(404, "nope")])
        with self.assertRaises(requests.HTTPError):
            c.get_xml("/a")
        self.assertEqual(c.session.get.call_count, 1)
        self.assertEqual(sleeps, [])

    def test_connection_error_is_retried(self):
        c, sleeps = client_with([requests.ConnectionError("boom"), resp(200, "<ok/>")])
        self.assertEqual(c.get_xml("/a"), b"<ok/>")
        self.assertEqual(len(sleeps), 1)


class TestMisc(unittest.TestCase):
    def test_timeout_is_always_passed(self):
        c, _ = client_with([resp(200)], timeout=12.5)
        c.get_xml("/a")
        self.assertEqual(c.session.get.call_args.kwargs["timeout"], 12.5)

    def test_throttle_waits_between_calls(self):
        now = [100.0]
        sleeps = []
        c = SAPClient(make_config(request_delay=0.5), sleep=lambda s: (sleeps.append(s), now.__setitem__(0, now[0] + s)),
                      clock=lambda: now[0])
        c.session.get = MagicMock(side_effect=[resp(200), resp(200)])
        c.get_xml("/a")
        c.get_xml("/b")
        self.assertEqual(len(sleeps), 1)
        self.assertAlmostEqual(sleeps[0], 0.5)

    def test_request_counter_and_xml_is_bytes(self):
        c, _ = client_with([resp(200, "<a>M\u00fcller</a>"), resp(200, "{}")])
        self.assertIsInstance(c.get_xml("/a"), bytes)
        c.get_json("/b")
        self.assertEqual(c.request_count, 2)

    def test_apikey_header_set(self):
        c = SAPClient(make_config())
        self.assertEqual(c.session.headers["APIKey"], "SECRETKEY123")


if __name__ == "__main__":
    unittest.main()
