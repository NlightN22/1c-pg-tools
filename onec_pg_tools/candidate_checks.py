"""Shared safety checks for index candidates."""

from __future__ import annotations

from onec_pg_tools.repository import fetch_index_by_name


def is_candidate_safe(conn, db_config, candidate, index_name, logger) -> bool:
    if not candidate.owner_allowed:
        logger.error(
            "database=%s table=%s skipped_not_owner owner=%s",
            db_config.name,
            candidate.table_name,
            candidate.owner_name,
        )
        return False

    existing_index = fetch_index_by_name(conn, index_name)
    if existing_index:
        logger.error(
            "database=%s table=%s skipped_index_name_exists index=%s "
            "indisvalid=%s indisready=%s definition=%s",
            db_config.name,
            candidate.table_name,
            index_name,
            existing_index["indisvalid"],
            existing_index["indisready"],
            existing_index["index_definition"],
        )
        return False
    return True
