"""Cron-friendly pending index check."""

from __future__ import annotations

import logging
import sys
from contextlib import closing

from onec_pg_tools.candidate_checks import is_candidate_safe
from onec_pg_tools.config import DatabaseConfig, PostgresConfig
from onec_pg_tools.index_sql import build_create_index_sql, make_index_name
from onec_pg_tools.postgres import connect
from onec_pg_tools.repository import database_exists, fetch_candidates
from onec_pg_tools.repository import fetch_prerequisites, is_primary


PENDING_CHECK_FAILED = 2


def collect_pending_indexes(
    postgres: PostgresConfig,
    db_config: DatabaseConfig,
    logger: logging.LoggerAdapter,
) -> list[str]:
    pending_indexes = []
    with closing(connect(postgres, db_config.name)) as conn:
        primary = is_primary(conn)
        logger.info("database=%s primary=%s", db_config.name, primary)

        prerequisites = fetch_prerequisites(conn)
        for key, value in prerequisites.items():
            logger.info(
                "database=%s prerequisite=%s value=%s",
                db_config.name,
                key,
                value,
            )
        if not prerequisites["has_mchar_mvarchar"]:
            raise RuntimeError(f"database={db_config.name} required_types_missing")

        candidates = fetch_candidates(conn, db_config)
        logger.info("database=%s candidates=%d", db_config.name, len(candidates))

        for candidate in candidates:
            index_name = make_index_name(candidate.table_name)
            if not is_candidate_safe(conn, db_config, candidate, index_name, logger):
                continue

            create_sql_text = build_create_index_sql(candidate).as_string(conn)
            pending_indexes.append(
                f"database={db_config.name} "
                f"table={candidate.table_name} "
                f"size={candidate.table_size_pretty} "
                f"sql={create_sql_text};"
            )

    return pending_indexes


def process_pending_mode(
    admin_conn,
    postgres: PostgresConfig,
    enabled_databases: list[DatabaseConfig],
    logger: logging.LoggerAdapter,
) -> int:
    pending_indexes = []
    errors = []

    for db_config in enabled_databases:
        if not database_exists(admin_conn, db_config.name):
            errors.append(f"database={db_config.name} missing_or_not_connectable")
            logger.error("database=%s missing_or_not_connectable", db_config.name)
            continue

        try:
            pending_indexes.extend(collect_pending_indexes(postgres, db_config, logger))
        except Exception as exc:  # noqa: BLE001 - pending must report all check errors.
            errors.append(f"database={db_config.name} error={exc}")
            logger.exception("database=%s failed error=%s", db_config.name, exc)

    if errors:
        print("Pending index check failed:", file=sys.stderr)
        for error in errors:
            print(error, file=sys.stderr)
        return PENDING_CHECK_FAILED

    if not pending_indexes:
        print("No pending indexes.")
        return 0

    for pending_index in pending_indexes:
        print(pending_index)
    return 1
