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
    auth_mode: str          # "apikey" or "basic"
    supplier_top: int
    po_top: int
    invoice_top: int


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


def load_config() -> AppConfig:
    """Load configuration from environment / .env file."""
    load_dotenv()

    sap = SAPConfig(
        base_url=os.getenv("SAP_BASE_URL", "").rstrip("/"),
        api_key=os.getenv("SAP_API_KEY", ""),
        username=os.getenv("SAP_USERNAME", ""),
        password=os.getenv("SAP_PASSWORD", ""),
        auth_mode=os.getenv("SAP_AUTH_MODE", "none"),
        supplier_top=int(os.getenv("SUPPLIER_TOP", "800")),
        po_top=int(os.getenv("PO_TOP", "5000")),
        invoice_top=int(os.getenv("INVOICE_TOP", "5000")),
    )

    pg = PGConfig(
        host=os.getenv("PG_HOST", "localhost"),
        port=int(os.getenv("PG_PORT", "5432")),
        database=os.getenv("PG_DATABASE", "sap_connector"),
        user=os.getenv("PG_USER", "postgres"),
        password=os.getenv("PG_PASSWORD", "postgres"),
    )

    return AppConfig(sap=sap, pg=pg)
