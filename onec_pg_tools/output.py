"""Console output helpers."""

from __future__ import annotations

from typing import Any, Iterable


def print_rows(rows: Iterable[dict[str, Any]]) -> None:
    rows = list(rows)
    if not rows:
        print("No rows.")
        return

    headers = list(rows[0].keys())
    widths = {
        header: max(len(str(header)), *(len(str(row.get(header, ""))) for row in rows))
        for header in headers
    }
    print(" | ".join(header.ljust(widths[header]) for header in headers))
    print("-+-".join("-" * widths[header] for header in headers))
    for row in rows:
        print(
            " | ".join(
                str(row.get(header, "")).ljust(widths[header]) for header in headers
            )
        )
