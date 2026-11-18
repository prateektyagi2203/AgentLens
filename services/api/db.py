"""DuckDB connection helper. One embedded file; schema.sql is applied idempotently on connect."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from . import settings

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(path: str | Path | None = None, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    target = Path(path) if path else settings.db_path()
    if str(target) != ":memory:":
        target.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(target), read_only=read_only)
    if not read_only:
        con.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
    return con


def one(con: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None) -> tuple[Any, ...] | None:
    """First row or None. Fully drains the result so the connection is never left with an open cursor."""
    rows = con.execute(sql, params or []).fetchall()
    return rows[0] if rows else None
