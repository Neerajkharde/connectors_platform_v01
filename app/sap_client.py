"""
SAP HTTP client — handles OData V2 (XML) and OData V4 (JSON) requests
with configurable authentication (API-key header or HTTP Basic).

Beyond plain GETs it protects the (rate-limited) SAP API Business Hub:

* **Throttle**   – a minimum delay between two calls.
* **Retry**      – temporary errors (HTTP 429, spike-arrest, 502/503/504,
                   connection problems) are retried with back-off and honour
                   ``Retry-After``.
* **Fail fast**  – a *quota* error (``policies.ratelimit.QuotaViolation``) is
                   NOT temporary: retrying only burns more quota.  The client
                   raises :class:`SAPQuotaExceeded` and refuses to send any
                   further request.
* **Timeout**    – no call can hang forever.
* **Redaction**  – API keys / passwords are never printed in diagnostics.
"""

import json
import time

import requests

from app.config import SAPConfig

SENSITIVE_HEADERS = {"apikey", "authorization", "x-api-key", "cookie", "set-cookie"}


class SAPError(Exception):
    """Base class for SAP client errors."""


class SAPQuotaExceeded(SAPError):
    """The API key's quota is used up – waiting (not retrying) is required."""


class SAPClient:
    """Thin wrapper around ``requests.Session`` for SAP OData calls."""

    def __init__(self, config: SAPConfig, sleep=time.sleep, clock=time.monotonic):
        self.config = config
        self.session = requests.Session()
        self.request_count = 0          # every HTTP call that was sent
        self._quota_blocked: str | None = None
        self._last_call = 0.0
        self._sleep = sleep             # injectable for tests
        self._clock = clock

        self.session.headers.update({"Accept-Encoding": "gzip, deflate"})

        if config.auth_mode == "apikey" and config.api_key:
            self.session.headers["APIKey"] = config.api_key
        elif config.auth_mode == "basic":
            self.session.auth = (config.username, config.password)
        # auth_mode == "none" -> no auth headers

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @staticmethod
    def _redact(headers) -> dict:
        return {
            k: ("***redacted***" if k.lower() in SENSITIVE_HEADERS else v)
            for k, v in dict(headers).items()
        }

    def _scrub(self, text: str) -> str:
        """Remove the API key / password from free text.

        SAP's quota error echoes the API key in its message body
        ("... Identifier : <your key>"), so redacting headers alone is not enough.
        """
        for secret in (self.config.api_key, self.config.password):
            if secret:
                text = text.replace(secret, "***redacted***")
        return text

    def _dump_failure(self, resp: requests.Response) -> None:
        """Print diagnostic info when a request fails (secrets removed)."""
        print(f"\n{'-' * 60}")
        print(f"  [DIAG] HTTP {resp.status_code}  {resp.request.method}  {self._scrub(resp.url)}")
        print(f"  [DIAG] Request headers : {self._redact(resp.request.headers)}")
        print(f"  [DIAG] Response headers: {self._redact(resp.headers)}")
        print(f"  [DIAG] Response body   :\n{self._scrub(resp.text[:2000])}")
        print(f"{'-' * 60}\n")

    # ------------------------------------------------------------------
    # Error classification
    # ------------------------------------------------------------------

    @staticmethod
    def _fault_code(resp: requests.Response) -> str:
        """Apigee error code, e.g. ``policies.ratelimit.QuotaViolation``."""
        try:
            return str(json.loads(resp.text)["fault"]["detail"]["errorcode"]).lower()
        except (ValueError, KeyError, TypeError):
            return ""

    def _classify(self, resp: requests.Response) -> str:
        """Return ``'quota'``, ``'retry'`` or ``'fatal'`` for a non-OK response."""
        code = self._fault_code(resp)
        body = resp.text[:2000].lower()
        if "quotaviolation" in code or "quota limit" in body:
            return "quota"
        if "spikearrest" in code or resp.status_code == 429:
            return "retry"
        if resp.status_code in (502, 503, 504):
            return "retry"
        return "fatal"

    def _backoff(self, attempt: int, resp: requests.Response | None, why: str) -> None:
        wait = min(2 ** attempt * 2.0, 60.0)
        if resp is not None:
            retry_after = resp.headers.get("Retry-After", "")
            if retry_after.isdigit():
                wait = min(float(retry_after), 120.0)
        print(f"  [RETRY] {why} - waiting {wait:.0f}s (attempt {attempt + 1}/{self.config.max_retries})")
        self._sleep(wait)

    # ------------------------------------------------------------------
    # Core request
    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        delay = self.config.request_delay
        if delay > 0 and self._last_call:
            remaining = delay - (self._clock() - self._last_call)
            if remaining > 0:
                self._sleep(remaining)
        self._last_call = self._clock()

    def _request(self, url: str, accept: str, params: dict | None = None) -> requests.Response:
        for attempt in range(self.config.max_retries + 1):
            if self._quota_blocked:
                raise SAPQuotaExceeded(self._quota_blocked)

            self._throttle()
            try:
                resp = self.session.get(
                    url, params=params, headers={"Accept": accept},
                    timeout=self.config.timeout,
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt >= self.config.max_retries:
                    raise
                self._backoff(attempt, None, f"{type(exc).__name__}")
                continue

            self.request_count += 1
            if resp.ok:
                return resp

            kind = self._classify(resp)
            if kind == "quota":
                self._dump_failure(resp)
                self._quota_blocked = (
                    "SAP API quota exceeded (policies.ratelimit.QuotaViolation). "
                    "Retrying does not help - wait for the quota window to reset "
                    "or use a different API key."
                )
                raise SAPQuotaExceeded(self._quota_blocked)
            if kind == "retry" and attempt < self.config.max_retries:
                self._backoff(attempt, resp, f"HTTP {resp.status_code} (temporary)")
                continue

            self._dump_failure(resp)
            resp.raise_for_status()
        raise SAPError("unreachable")  # pragma: no cover

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get_xml(self, path: str, params: dict | None = None) -> bytes:
        """GET an OData V2 resource and return the raw XML **bytes**.

        Bytes (not ``resp.text``) are returned on purpose: the XML parser then
        honours the encoding declared in the XML itself.  ``resp.text`` has to
        *guess* the charset for ``application/atom+xml`` and can corrupt names
        such as "Müller".
        """
        resp = self._request(f"{self.config.base_url}{path}", "application/atom+xml", params)
        return resp.content

    def get_json(self, path: str, params: dict | None = None) -> dict:
        """GET an OData V4 resource and return the parsed JSON."""
        resp = self._request(f"{self.config.base_url}{path}", "application/json", params)
        return resp.json()

    def get_full_url_xml(self, full_url: str) -> bytes:
        """GET a fully-qualified OData V2 URL (for navigation links)."""
        return self._request(full_url, "application/atom+xml").content
