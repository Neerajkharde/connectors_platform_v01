"""
Configuration module — loads SAP and PostgreSQL settings from
environment variables or a .env file.
"""

import os
from dataclasses import dataclass
from dotenv import load_dotenv


@dataclass(frozen=True)
class SAPConfig:
    base_url: str
    api_key: str
    username: str
    password: str
    auth_mode: str          # "none", "apikey" or "basic"
    supplier_top: int       # max suppliers to extract
    po_top: int             # max purchase orders to extract
    invoice_top: int        # max invoice headers / PO references to extract
    item_top: int = 20000   # max purchase-order items to extract
    page_size: int = 50     # records per HTTP page ($top)
    filter_chunk: int = 20  # keys combined into one $filter (a OR b OR ...)
    use_expand: bool = True # fetch supplier sub-collections with $expand
    request_delay: float = 0.25  # min seconds between SAP calls (throttle)
    max_retries: int = 3    # retries for temporary errors (spike arrest, 503...)
    timeout: float = 60.0   # seconds before a SAP call is abandoned


@dataclass(frozen=True)
class PGConfig:
    host: str
    port: int
    database: str
    user: str
    password: str


@dataclass(frozen=True)
class AppConfig:
    sap: SAPConfig
    pg: PGConfig


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "y")


def load_config() -> AppConfig:
    """Load configuration from environment / .env file."""
    load_dotenv()

    sap = SAPConfig(
        base_url=os.getenv("SAP_BASE_URL", "").rstrip("/"),
        api_key=os.getenv("SAP_API_KEY", ""),
        username=os.getenv("SAP_USERNAME", ""),
        password=os.getenv("SAP_PASSWORD", ""),
        auth_mode=os.getenv("SAP_AUTH_MODE", "apikey").strip().lower(),
        supplier_top=int(os.getenv("SUPPLIER_TOP", "800")),
        po_top=int(os.getenv("PO_TOP", "5000")),
        invoice_top=int(os.getenv("INVOICE_TOP", "5000")),
        item_top=int(os.getenv("ITEM_TOP", "20000")),
        page_size=int(os.getenv("SAP_PAGE_SIZE", "50")),
        filter_chunk=int(os.getenv("SAP_FILTER_CHUNK", "20")),
        use_expand=_env_bool("SAP_USE_EXPAND", True),
        request_delay=float(os.getenv("SAP_REQUEST_DELAY", "0.25")),
        max_retries=int(os.getenv("SAP_MAX_RETRIES", "3")),
        timeout=float(os.getenv("SAP_TIMEOUT", "60")),
    )

    if not sap.base_url:
        raise ValueError("SAP_BASE_URL is not set (check your .env file).")
    if sap.auth_mode == "apikey" and not sap.api_key:
        raise ValueError("SAP_AUTH_MODE=apikey but SAP_API_KEY is empty.")
    if sap.auth_mode == "basic" and not (sap.username and sap.password):
        raise ValueError("SAP_AUTH_MODE=basic but SAP_USERNAME / SAP_PASSWORD are empty.")

    pg = PGConfig(
        host=os.getenv("PG_HOST", "localhost"),
        port=int(os.getenv("PG_PORT", "5432")),
        database=os.getenv("PG_DATABASE", "sap_connector"),
        user=os.getenv("PG_USER", "postgres"),
        password=os.getenv("PG_PASSWORD", "postgres"),
    )

    return AppConfig(sap=sap, pg=pg)
