"""
PostgreSQL connection helper using psycopg2.
"""

import psycopg2
from app.config import PGConfig


def get_connection(config: PGConfig):
    """Return a new psycopg2 connection."""
    return psycopg2.connect(
        host=config.host,
        port=config.port,
        dbname=config.database,
        user=config.user,
        password=config.password,
    )
