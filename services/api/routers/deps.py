"""Shared plumbing for the routers: DB access, error type, filter parsing and window resolution.

DuckDB allows one read-write handle per file per process, so the API keeps a single shared connection and hands out a
fresh cursor per request. Cursors are independent transaction contexts, so reads never block on (or see half of) a
pipeline run; every write goes through `Database.write()`, which serializes writers with a lock.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import duckdb
from fastapi import Query

from .. import db, settings

SEGMENTS = ("all_agents", "verified", "declared", "suspected", "humans")
AGENT_CLASSES = ("user_fetcher", "browsing_agent", "search_crawler", "training_crawler")
STAGE_IDS = tuple(f"S{i}" for i in range(1, 9))


class ApiError(Exception):
    """Rendered by the app-level handler as {"error": {"code", "message", "fields"?}}."""

    def __init__(self, status: int, code: str, message: str, fields: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.fields = status, code, message, fields


def not_found(message: str) -> ApiError:
    return ApiError(404, "not_found", message)


def validation_error(message: str, fields: dict[str, str]) -> ApiError:
    return ApiError(422, "validation_error", message, fields)


class Database:
    """Lazily opened shared connection plus per-request cursors and a serialized write path."""

    def __init__(self) -> None:
        self._con: duckdb.DuckDBPyConnection | None = None
        self._open_lock = threading.Lock()
        self.write_lock = threading.RLock()
        self.version = 0

    def bump(self) -> None:
        """Mark the data as changed so memoised aggregates are recomputed."""
        self.version += 1

    def connection(self) -> duckdb.DuckDBPyConnection:
        with self._open_lock:
            if self._con is None:
                self._con = db.connect()
            return self._con

    def reset(self) -> None:
        """Close the shared connection (tests re-point AGENTLENS_DB_PATH, then the next request reopens)."""
        with self._open_lock:
            if self._con is not None:
                self._con.close()
            self._con = None
            self.bump()

    @contextmanager
    def read(self) -> Iterator[duckdb.DuckDBPyConnection]:
        cur = self.connection().cursor()
        try:
            yield cur
        finally:
            cur.close()

    @contextmanager
    def write(self, timeout_s: float = 10.0) -> Iterator[duckdb.DuckDBPyConnection]:
        if not self.write_lock.acquire(timeout=timeout_s):
            raise ApiError(409, "run_in_progress", "The database is busy with another write; retry shortly")
        cur = self.connection().cursor()
        try:
            yield cur
        finally:
            cur.close()
            self.bump()
            self.write_lock.release()

    def exists(self) -> bool:
        return self._con is not None or settings.db_path().exists()


DB = Database()


def get_read() -> Iterator[duckdb.DuckDBPyConnection]:
    """FastAPI dependency: a cursor for the lifetime of the request."""
    with DB.read() as cur:
        yield cur


@dataclass(frozen=True)
class Window:
    from_: str
    to: str
    days: int

    def as_dict(self) -> dict[str, Any]:
        return {"from": self.from_, "to": self.to, "days": self.days}

    def previous(self) -> Window:
        start = date.fromisoformat(self.from_)
        return Window((start - timedelta(days=self.days)).isoformat(), (start - timedelta(days=1)).isoformat(), self.days)


@dataclass(frozen=True)
class Filters:
    from_: str | None = None
    to: str | None = None
    segment: str = "all_agents"
    operator: str | None = None
    agent_class: str | None = None


def _day(value: str | None, name: str, errors: dict[str, str]) -> str | None:
    if not value:
        return None
    try:
        if len(value) == 10:
            return date.fromisoformat(value).isoformat()
    except ValueError:
        pass
    errors[name] = "must be a YYYY-MM-DD date"
    return None


def parse_filters(
    from_: str | None = None, to: str | None = None, segment: str | None = None, operator: str | None = None,
    agent_class: str | None = None,
) -> Filters:  # fmt: skip
    errors: dict[str, str] = {}
    f = _day(from_, "from", errors)
    t = _day(to, "to", errors)
    if segment and segment not in SEGMENTS:
        errors["segment"] = f"must be one of {', '.join(SEGMENTS)}"
    if agent_class and agent_class not in AGENT_CLASSES:
        errors["agent_class"] = f"must be one of {', '.join(AGENT_CLASSES)}"
    if errors:
        raise validation_error("Invalid filter parameters", errors)
    return Filters(f, t, segment or "all_agents", operator or None, agent_class or None)


def filters_dep(
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    segment: str | None = None,
    operator: str | None = None,
    agent_class: str | None = None,
) -> Filters:
    return parse_filters(from_, to, segment, operator, agent_class)


def data_bounds(cur: duckdb.DuckDBPyConnection) -> tuple[str, str] | None:
    row = db.one(cur, "SELECT CAST(min(start_ts) AS DATE), CAST(max(start_ts) AS DATE) FROM sessions")
    if not row or row[0] is None:
        return None
    return row[0].isoformat(), row[1].isoformat()


def resolve_window(cur: duckdb.DuckDBPyConnection, from_: str | None, to: str | None) -> Window:
    """Clamp the requested days to the data bounds (default: everything); a reversed range is swapped."""
    bounds = data_bounds(cur)
    if bounds is None:
        today = datetime.now(UTC).date().isoformat()
        return Window(today, today, 1)
    lo = from_ if from_ and from_ >= bounds[0] else bounds[0]
    hi = to if to and to <= bounds[1] else bounds[1]
    if lo > hi:
        lo, hi = hi, lo
    days = (date.fromisoformat(hi) - date.fromisoformat(lo)).days + 1
    return Window(lo, hi, days)


def iso(ts: Any) -> str | None:
    """Timestamps are stored as naive UTC; the wire format is ISO-8601 with a Z suffix."""
    if ts is None:
        return None
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(ts, datetime) else str(ts)


def slug(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
