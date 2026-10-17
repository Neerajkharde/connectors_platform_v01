"""
SAP HTTP client — handles OData V2 (XML) and OData V4 (JSON) requests
with configurable authentication (API-key header or HTTP Basic).
"""

import requests
from app.config import SAPConfig


class SAPClient:
    """Thin wrapper around ``requests.Session`` for SAP OData calls."""

    def __init__(self, config: SAPConfig):
        self.config = config
        self.session = requests.Session()

        # Common headers
        self.session.headers.update({
            "Accept-Encoding": "gzip, deflate",
        })

        if config.auth_mode == "apikey" and config.api_key:
            self.session.headers["APIKey"] = config.api_key
        elif config.auth_mode == "basic":
            self.session.auth = (config.username, config.password)
        # auth_mode == "none" → no auth headers (SAP sandbox is public)

    # ------------------------------------------------------------------
    # Internal diagnostics
    # ------------------------------------------------------------------

    @staticmethod
    def _dump_failure(resp: requests.Response) -> None:
        """Print diagnostic info when a request fails."""
        print(f"\n{'─'*60}")
        print(f"  [DIAG] HTTP {resp.status_code}  {resp.request.method}  {resp.url}")
        print(f"  [DIAG] Request headers : {dict(resp.request.headers)}")
        print(f"  [DIAG] Response headers: {dict(resp.headers)}")
        body = resp.text[:2000]  # cap to 2 KB to avoid flooding the terminal
        print(f"  [DIAG] Response body   :\n{body}")
        print(f"{'─'*60}\n")

    def _checked(self, resp: requests.Response) -> requests.Response:
        """Call raise_for_status, but dump the body first on failure."""
        if not resp.ok:
            self._dump_failure(resp)
        resp.raise_for_status()
        return resp

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get_xml(self, path: str, params: dict | None = None) -> str:
        """GET an OData V2 resource and return the raw XML text."""
        url = f"{self.config.base_url}{path}"
        headers = {"Accept": "application/atom+xml"}
        resp = self.session.get(url, params=params, headers=headers)
        self._checked(resp)
        return resp.text

    def get_json(self, path: str, params: dict | None = None) -> dict:
        """GET an OData V4 resource and return the parsed JSON."""
        url = f"{self.config.base_url}{path}"
        headers = {"Accept": "application/json"}
        resp = self.session.get(url, params=params, headers=headers)
        self._checked(resp)
        return resp.json()

    def get_full_url_xml(self, full_url: str) -> str:
        """GET a fully-qualified OData V2 URL (for navigation links)."""
        headers = {"Accept": "application/atom+xml"}
        resp = self.session.get(full_url, headers=headers)
        self._checked(resp)
        return resp.text
