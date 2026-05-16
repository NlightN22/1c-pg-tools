"""SQL builders for managed 1C number indexes."""

from __future__ import annotations

import hashlib

from psycopg2 import sql

from onec_pg_tools.repository import CandidateTable


INDEX_SUFFIX = "_number_as_mvarchar"
MAX_IDENTIFIER_BYTES = 63


def make_index_name(table_name: str) -> str:
    index_base = table_name.lstrip("_") or table_name
    index_name = f"idx_{index_base}{INDEX_SUFFIX}"
    if len(index_name.encode("utf-8")) <= MAX_IDENTIFIER_BYTES:
        return index_name

    digest = hashlib.sha1(table_name.encode("utf-8")).hexdigest()[:8]
    suffix = f"_{digest}{INDEX_SUFFIX}"
    prefix_budget = MAX_IDENTIFIER_BYTES - len("idx_".encode()) - len(
        suffix.encode("utf-8")
    )
    encoded = index_base.encode("utf-8")[:prefix_budget]
    safe_prefix = encoded.decode("utf-8", errors="ignore").rstrip("_")
    return f"idx_{safe_prefix}{suffix}"


def build_create_index_sql(candidate: CandidateTable) -> sql.Composed:
    return sql.SQL(
        "CREATE INDEX CONCURRENTLY {index_name} "
        "ON public.{table_name} "
        "USING btree ((({column_name})::mvarchar))"
    ).format(
        index_name=sql.Identifier(make_index_name(candidate.table_name)),
        table_name=sql.Identifier(candidate.table_name),
        column_name=sql.Identifier(candidate.column_name),
    )


def build_analyze_sql(candidate: CandidateTable) -> sql.Composed:
    return sql.SQL("ANALYZE public.{table_name}").format(
        table_name=sql.Identifier(candidate.table_name)
    )
