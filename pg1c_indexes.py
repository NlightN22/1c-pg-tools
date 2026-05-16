#!/usr/bin/env python3
"""Create and report 1C number expression indexes for PostgreSQL databases."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import psycopg2  # noqa: F401
    import yaml  # noqa: F401
except ImportError as exc:  # pragma: no cover - handled at runtime for admins.
    print(
        "Missing dependency. Install requirements with: "
        "python3 -m pip install -r requirements.txt",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc

from onec_pg_tools.config import DatabaseConfig, PostgresConfig, configure_pgpass
from onec_pg_tools.config import load_config
from onec_pg_tools.index_sql import build_analyze_sql, build_create_index_sql
from onec_pg_tools.index_sql import make_index_name
from onec_pg_tools.output import print_rows
from onec_pg_tools.postgres import connect
from onec_pg_tools.repository import database_exists, fetch_candidates
from onec_pg_tools.repository import fetch_cluster_databases
from onec_pg_tools.repository import fetch_invalid_index_by_name
from onec_pg_tools.repository import fetch_invalid_indexes, fetch_prerequisites
from onec_pg_tools.repository import fetch_report, is_primary


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = SCRIPT_DIR / "config.yaml"
DEFAULT_LOG_DIR = Path("/var/log/1c-pg-tools")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manage 1C _number::mvarchar expression indexes."
    )
    parser.add_argument(
        "mode",
        choices=("list-databases", "dry-run", "run", "report", "check-invalid"),
        help="Execution mode.",
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to config.yaml.",
    )
    parser.add_argument(
        "--log-dir",
        default=str(DEFAULT_LOG_DIR),
        help="Directory for daily log files.",
    )
    return parser.parse_args()


def setup_logging(mode: str, log_dir: Path) -> logging.LoggerAdapter:
    logger = logging.getLogger("pg1c_indexes")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s mode=%(mode)s %(message)s"
    )
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"ensure_indexes_{datetime.now():%Y-%m-%d}.log"
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError as exc:
        logger.warning(
            "file_logging_unavailable log_dir=%s error=%s",
            log_dir,
            exc,
            extra={"mode": mode},
        )

    return logging.LoggerAdapter(logger, {"mode": mode})


def process_dry_run_or_run(
    mode: str,
    postgres: PostgresConfig,
    db_config: DatabaseConfig,
    logger: logging.LoggerAdapter,
) -> None:
    with connect(postgres, db_config.name) as conn:
        primary = is_primary(conn)
        logger.info("database=%s primary=%s", db_config.name, primary)
        if mode == "run" and not primary:
            logger.error("database=%s refused_not_primary", db_config.name)
            return

        prerequisites = fetch_prerequisites(conn)
        for key, value in prerequisites.items():
            logger.info("database=%s prerequisite=%s value=%s", db_config.name, key, value)
        if not prerequisites["has_mchar_mvarchar"] or not prerequisites["has_mvarchar_icase_ops"]:
            logger.error("database=%s required_types_or_opclass_missing", db_config.name)
            return

        candidates = fetch_candidates(conn, db_config)
        logger.info("database=%s candidates=%d", db_config.name, len(candidates))

        for candidate in candidates:
            create_sql = build_create_index_sql(candidate)
            create_sql_text = create_sql.as_string(conn)
            index_name = make_index_name(candidate.table_name)
            print(f"-- database: {db_config.name}")
            print(f"-- table_size: {candidate.table_size_pretty}")
            print(create_sql_text + ";")

            logger.info(
                "database=%s table=%s size=%s sql=%s",
                db_config.name,
                candidate.table_name,
                candidate.table_size_pretty,
                create_sql_text,
            )
            if not is_candidate_safe(conn, db_config, candidate, index_name, logger):
                continue
            if mode == "dry-run":
                continue
            create_index(conn, db_config, candidate, index_name, create_sql, logger)


def is_candidate_safe(conn, db_config, candidate, index_name, logger) -> bool:
    if not candidate.owner_allowed:
        logger.error(
            "database=%s table=%s skipped_not_owner owner=%s",
            db_config.name,
            candidate.table_name,
            candidate.owner_name,
        )
        return False

    invalid_index = fetch_invalid_index_by_name(conn, index_name)
    if invalid_index:
        logger.error(
            "database=%s table=%s skipped_invalid_index_exists index=%s",
            db_config.name,
            candidate.table_name,
            index_name,
        )
        return False
    return True


def create_index(conn, db_config, candidate, index_name, create_sql, logger) -> None:
    started = time.monotonic()
    try:
        with conn.cursor() as cur:
            cur.execute(create_sql)
            if db_config.analyze_after_create:
                cur.execute(build_analyze_sql(candidate))
        elapsed = time.monotonic() - started
        logger.info(
            "database=%s table=%s index=%s created elapsed_sec=%.3f",
            db_config.name,
            candidate.table_name,
            index_name,
            elapsed,
        )
    except Exception as exc:  # noqa: BLE001 - log and continue with next table.
        elapsed = time.monotonic() - started
        logger.exception(
            "database=%s table=%s index=%s failed elapsed_sec=%.3f error=%s",
            db_config.name,
            candidate.table_name,
            index_name,
            elapsed,
            exc,
        )


def process_report_mode(postgres: PostgresConfig, db_config: DatabaseConfig) -> None:
    with connect(postgres, db_config.name) as conn:
        rows = fetch_report(conn)
        print(f"\n# database: {db_config.name}")
        print_rows(rows)


def process_check_invalid_mode(
    postgres: PostgresConfig, db_config: DatabaseConfig
) -> None:
    with connect(postgres, db_config.name) as conn:
        rows = fetch_invalid_indexes(conn)
        print(f"\n# database: {db_config.name}")
        print_rows(rows)


def process_list_databases_mode(admin_conn, configured_databases: list[DatabaseConfig]) -> None:
    configured = {database.name: database for database in configured_databases}
    rows = []
    for row in fetch_cluster_databases(admin_conn):
        database_name = row["database_name"]
        configured_database = configured.get(database_name)
        rows.append(
            {
                "database_name": database_name,
                "owner_name": row["owner_name"],
                "database_size": row["database_size"],
                "allow_connections": row["allow_connections"],
                "can_connect": row["can_connect"],
                "encoding": row["encoding"],
                "configured": configured_database is not None,
                "enabled": bool(configured_database.enabled)
                if configured_database is not None
                else False,
            }
        )
    print_rows(rows)


def process_database(mode, postgres, db_config, logger) -> None:
    if mode in ("dry-run", "run"):
        process_dry_run_or_run(mode, postgres, db_config, logger)
    elif mode == "report":
        process_report_mode(postgres, db_config)
    elif mode == "check-invalid":
        process_check_invalid_mode(postgres, db_config)


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).resolve()
    logger = setup_logging(args.mode, Path(args.log_dir))
    configure_pgpass(SCRIPT_DIR)

    logger.info("started config=%s", config_path)
    postgres, databases = load_config(config_path)
    enabled_databases = [database for database in databases if database.enabled]
    logger.info(
        "postgres_host=%s postgres_port=%s enabled_databases=%d",
        postgres.host,
        postgres.port,
        len(enabled_databases),
    )

    with connect(postgres, postgres.connect_db) as admin_conn:
        if args.mode == "list-databases":
            process_list_databases_mode(admin_conn, databases)
            logger.info("finished")
            return 0

        for db_config in enabled_databases:
            if not database_exists(admin_conn, db_config.name):
                logger.error("database=%s missing_or_not_connectable", db_config.name)
                continue
            try:
                process_database(args.mode, postgres, db_config, logger)
            except Exception as exc:  # noqa: BLE001 - keep other databases processable.
                logger.exception("database=%s failed error=%s", db_config.name, exc)

    logger.info("finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
