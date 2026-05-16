"""PostgreSQL connection helpers."""

from __future__ import annotations

import psycopg2

from onec_pg_tools.config import PostgresConfig


def connect(postgres: PostgresConfig, database: str):
    conn = psycopg2.connect(
        host=postgres.host,
        port=postgres.port,
        user=postgres.user,
        dbname=database,
        connect_timeout=10,
        application_name="1c-pg-tools-ensure-indexes",
    )
    conn.autocommit = True
    return conn
