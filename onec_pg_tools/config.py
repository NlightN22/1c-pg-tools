"""Configuration loading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class PostgresConfig:
    host: str
    port: int
    user: str
    connect_db: str


@dataclass(frozen=True)
class DatabaseConfig:
    name: str
    enabled: bool
    min_table_size_gb: float
    include_document_journals: bool
    include_tasks: bool
    analyze_after_create: bool


def load_config(path: Path) -> tuple[PostgresConfig, list[DatabaseConfig]]:
    with path.open("r", encoding="utf-8") as config_file:
        raw = yaml.safe_load(config_file) or {}

    postgres_raw = raw.get("postgres") or {}
    defaults = raw.get("defaults") or {}
    database_raw = raw.get("databases") or []

    postgres = PostgresConfig(
        host=str(postgres_raw["host"]),
        port=int(postgres_raw.get("port", 5432)),
        user=str(postgres_raw["user"]),
        connect_db=str(postgres_raw.get("connect_db", "postgres")),
    )

    databases = []
    for item in database_raw:
        databases.append(
            DatabaseConfig(
                name=str(item["name"]),
                enabled=bool(item.get("enabled", False)),
                min_table_size_gb=float(
                    item.get("min_table_size_gb", defaults.get("min_table_size_gb", 1))
                ),
                include_document_journals=bool(
                    item.get(
                        "include_document_journals",
                        defaults.get("include_document_journals", False),
                    )
                ),
                include_tasks=bool(
                    item.get("include_tasks", defaults.get("include_tasks", True))
                ),
                analyze_after_create=bool(
                    item.get(
                        "analyze_after_create",
                        defaults.get("analyze_after_create", True),
                    )
                ),
            )
        )

    return postgres, databases
