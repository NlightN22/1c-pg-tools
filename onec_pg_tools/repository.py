"""Database queries used by the index maintenance tool."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from psycopg2.extras import RealDictCursor

from onec_pg_tools.config import DatabaseConfig


@dataclass(frozen=True)
class CandidateTable:
    table_name: str
    column_name: str
    column_type: str
    total_size_bytes: int
    table_size_pretty: str
    owner_name: str
    owner_allowed: bool


def database_exists(admin_conn, database_name: str) -> bool:
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT datallowconn
            FROM pg_database
            WHERE datname = %s
            """,
            (database_name,),
        )
        row = cur.fetchone()
    return bool(row and row[0])


def fetch_cluster_databases(admin_conn) -> list[dict[str, Any]]:
    with admin_conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                d.datname AS database_name,
                owner.rolname AS owner_name,
                d.datallowconn AS allow_connections,
                pg_size_pretty(pg_database_size(d.datname)) AS database_size,
                pg_database_size(d.datname) AS database_size_bytes,
                pg_encoding_to_char(d.encoding) AS encoding,
                has_database_privilege(d.datname, 'CONNECT') AS can_connect
            FROM pg_database d
            JOIN pg_roles owner ON owner.oid = d.datdba
            WHERE NOT d.datistemplate
            ORDER BY pg_database_size(d.datname) DESC, d.datname
            """
        )
        return list(cur.fetchall())


def is_primary(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT NOT pg_is_in_recovery()")
        return bool(cur.fetchone()[0])


def fetch_prerequisites(conn) -> dict[str, Any]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT COUNT(DISTINCT typname) AS type_count
            FROM pg_type
            WHERE typname IN ('mchar', 'mvarchar')
            """
        )
        type_count = int(cur.fetchone()["type_count"])

        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_opclass opc
                JOIN pg_am am ON am.oid = opc.opcmethod
                WHERE opc.opcname = 'mvarchar_icase_ops'
                  AND am.amname = 'btree'
            ) AS exists
            """
        )
        has_opclass = bool(cur.fetchone()["exists"])

        cur.execute(
            "SELECT has_schema_privilege(current_user, 'public', 'CREATE') AS can_create"
        )
        can_create_public = bool(cur.fetchone()["can_create"])

    return {
        "has_mchar_mvarchar": type_count == 2,
        "has_mvarchar_icase_ops": has_opclass,
        "can_create_public": can_create_public,
    }


def fetch_candidates(conn, db_config: DatabaseConfig) -> list[CandidateTable]:
    min_size_bytes = int(db_config.min_table_size_gb * 1024 * 1024 * 1024)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                c.relname AS table_name,
                a.attname AS column_name,
                t.typname AS column_type,
                pg_total_relation_size(c.oid) AS total_size_bytes,
                pg_size_pretty(pg_total_relation_size(c.oid)) AS table_size_pretty,
                owner.rolname AS owner_name,
                (
                    (SELECT rolsuper FROM pg_roles WHERE rolname = current_user)
                    OR pg_has_role(c.relowner, 'MEMBER')
                ) AS owner_allowed
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_attribute a ON a.attrelid = c.oid
            JOIN pg_type t ON t.oid = a.atttypid
            JOIN pg_roles owner ON owner.oid = c.relowner
            WHERE n.nspname = 'public'
              AND c.relkind = 'r'
              AND NOT a.attisdropped
              AND lower(a.attname) = '_number'
              AND t.typname IN ('mchar', 'mvarchar')
              AND pg_total_relation_size(c.oid) >= %s
              AND (
                  lower(c.relname) LIKE '\_document%%' ESCAPE '\'
                  OR (%s AND lower(c.relname) LIKE '\_task%%' ESCAPE '\')
                  OR (%s AND lower(c.relname) LIKE '\_documentjournal%%' ESCAPE '\')
              )
              AND NOT (
                  lower(c.relname) LIKE '\_documentjournal%%' ESCAPE '\'
                  AND NOT %s
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM pg_index i
                  JOIN pg_class idx ON idx.oid = i.indexrelid
                  WHERE i.indrelid = c.oid
                    AND i.indisvalid
                    AND i.indisready
                    AND i.indexprs IS NOT NULL
                    AND pg_get_expr(i.indexprs, i.indrelid) ILIKE '%%mvarchar%%'
                    AND pg_get_expr(i.indexprs, i.indrelid) ILIKE '%%_number%%'
                    AND pg_get_indexdef(i.indexrelid) ILIKE '%%mvarchar_icase_ops%%'
              )
            ORDER BY pg_total_relation_size(c.oid) DESC, c.relname
            """,
            (
                min_size_bytes,
                db_config.include_tasks,
                db_config.include_document_journals,
                db_config.include_document_journals,
            ),
        )
        rows = cur.fetchall()

    return [
        CandidateTable(
            table_name=row["table_name"],
            column_name=row["column_name"],
            column_type=row["column_type"],
            total_size_bytes=int(row["total_size_bytes"]),
            table_size_pretty=row["table_size_pretty"],
            owner_name=row["owner_name"],
            owner_allowed=bool(row["owner_allowed"]),
        )
        for row in rows
    ]


def fetch_invalid_index_by_name(conn, index_name: str) -> dict[str, Any] | None:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                idx.relname AS index_name,
                i.indisvalid,
                i.indisready,
                pg_get_indexdef(idx.oid) AS index_definition
            FROM pg_index i
            JOIN pg_class idx ON idx.oid = i.indexrelid
            JOIN pg_namespace ns ON ns.oid = idx.relnamespace
            WHERE ns.nspname = 'public'
              AND idx.relname = %s
              AND (NOT i.indisvalid OR NOT i.indisready)
            """,
            (index_name,),
        )
        return cur.fetchone()


def fetch_report(conn) -> list[dict[str, Any]]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                current_database() AS database_name,
                ns.nspname AS schema_name,
                tbl.relname AS table_name,
                idx.relname AS index_name,
                pg_size_pretty(pg_total_relation_size(tbl.oid)) AS table_size,
                pg_size_pretty(pg_relation_size(idx.oid)) AS index_size,
                COALESCE(s.idx_scan, 0) AS idx_scan,
                COALESCE(s.idx_tup_read, 0) AS idx_tup_read,
                COALESCE(s.idx_tup_fetch, 0) AS idx_tup_fetch,
                now() AS checked_at
            FROM pg_index i
            JOIN pg_class idx ON idx.oid = i.indexrelid
            JOIN pg_class tbl ON tbl.oid = i.indrelid
            JOIN pg_namespace ns ON ns.oid = tbl.relnamespace
            LEFT JOIN pg_stat_user_indexes s ON s.indexrelid = idx.oid
            WHERE ns.nspname = 'public'
              AND idx.relname LIKE 'idx\\_%%\\_number\\_as\\_mvarchar%%' ESCAPE '\\'
            ORDER BY tbl.relname, idx.relname
            """
        )
        return list(cur.fetchall())


def fetch_invalid_indexes(conn) -> list[dict[str, Any]]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                current_database() AS database_name,
                ns.nspname AS schema_name,
                tbl.relname AS table_name,
                idx.relname AS index_name,
                i.indisvalid,
                i.indisready,
                pg_size_pretty(pg_relation_size(idx.oid)) AS index_size,
                pg_get_indexdef(idx.oid) AS index_definition
            FROM pg_index i
            JOIN pg_class idx ON idx.oid = i.indexrelid
            JOIN pg_class tbl ON tbl.oid = i.indrelid
            JOIN pg_namespace ns ON ns.oid = tbl.relnamespace
            WHERE ns.nspname = 'public'
              AND idx.relname LIKE 'idx\\_%%\\_number\\_as\\_mvarchar%%' ESCAPE '\\'
              AND (NOT i.indisvalid OR NOT i.indisready)
            ORDER BY tbl.relname, idx.relname
            """
        )
        return list(cur.fetchall())
