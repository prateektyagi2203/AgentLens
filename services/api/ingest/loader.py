"""Incremental, idempotent bulk loader: log files -> `requests` / `orders` / `annotations` (PRD 10.2).

Per file we remember a byte offset in `ingest_state` and only ever consume complete lines, so a line being
written while we read is picked up on the next run. Each block commits together with its new offset.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pyarrow as pa

from .. import db, settings
from .pages import load_rules, path_type_sql
from .parsers import (
    REQ_COLS,
    Batch,
    parse_jsonl_block,
    parse_nginx_block,
    parse_orders_block,
)

BLOCK_BYTES = 32 * 1024 * 1024
FORMATS = ("jsonl", "nginx_combined")

_STR = pa.string()
_ARROW_TYPES = {
    "ts": pa.timestamp("us"), "status": pa.int32(), "bytes_out": pa.int64(), "duration_ms": pa.int32(),
    "is_asset": pa.bool_(),
}  # fmt: skip
_REQ_SCHEMA = pa.schema([(c, _ARROW_TYPES.get(c, _STR)) for c in REQ_COLS])


@dataclass
class IngestResult:
    files: int = 0
    lines: int = 0
    requests_inserted: int = 0
    duplicates: int = 0
    errors: int = 0
    annotations: int = 0
    orders: int = 0
    per_file: dict[str, int] = field(default_factory=dict)

    def add(self, other: IngestResult) -> None:
        self.files += other.files
        self.lines += other.lines
        self.requests_inserted += other.requests_inserted
        self.duplicates += other.duplicates
        self.errors += other.errors
        self.annotations += other.annotations
        self.orders += other.orders
        self.per_file.update(other.per_file)

    def as_counts(self) -> dict[str, int]:
        return {
            "files": self.files, "lines": self.lines, "requests_inserted": self.requests_inserted,
            "duplicates": self.duplicates, "errors": self.errors, "annotations": self.annotations,
            "orders": self.orders,
        }  # fmt: skip


def _count_newlines(path: Path, upto: int) -> int:
    n, remaining = 0, upto
    with open(path, "rb") as fh:
        while remaining > 0:
            chunk = fh.read(min(remaining, 8 * 1024 * 1024))
            if not chunk:
                break
            n += chunk.count(b"\n")
            remaining -= len(chunk)
    return n


def _insert_requests(con: duckdb.DuckDBPyConnection, rows: list[tuple[object, ...]], source_name: str,
                     rules: list[tuple[str, str]]) -> None:  # fmt: skip
    cols = list(zip(*rows, strict=True))
    table = pa.Table.from_arrays(
        [pa.array(cols[i], type=_REQ_SCHEMA.field(i).type) for i in range(len(REQ_COLS))], schema=_REQ_SCHEMA
    )
    con.register("_ingest_stage", table)
    try:
        con.execute(
            f"""
            INSERT OR IGNORE INTO requests (
              request_id, ts, method, host, path, query, status, bytes_out, duration_ms, ip_hash, ip_prefix,
              user_agent, ua_hash, referer, accept, accept_language, sec_ch_ua, sec_fetch_site, sec_fetch_mode,
              sec_fetch_dest, has_signature, signature_agent, cookie_sid_hash, is_asset, event_type, page_type,
              error_code, ingested_at, source_file)
            SELECT request_id, ts, method, host, path, query, status, bytes_out, duration_ms, ip_hash, ip_prefix,
              user_agent, sha256(user_agent), referer, accept, accept_language, sec_ch_ua, sec_fetch_site,
              sec_fetch_mode, sec_fetch_dest, (signature IS NOT NULL OR signature_input IS NOT NULL),
              signature_agent_origin, cookie_sid_hash, is_asset OR pt = 'asset', event_type,
              CASE WHEN event_type = 'beacon' THEN 'beacon' WHEN is_asset THEN 'asset' ELSE pt END, error_code,
              current_timestamp::TIMESTAMP, ?
            FROM (
              SELECT *, {path_type_sql(rules)} AS pt
              FROM (SELECT DISTINCT ON (request_id) * FROM _ingest_stage)
            ) t
            """,
            [source_name],
        )
        con.execute(
            """
            INSERT OR IGNORE INTO request_signatures
              (request_id, signature, signature_input, signature_agent, method, authority, path)
            SELECT DISTINCT ON (s.request_id) s.request_id, s.signature, s.signature_input, s.signature_agent,
                   s.method, s.host, s.path
            FROM _ingest_stage s
            WHERE s.signature IS NOT NULL OR s.signature_input IS NOT NULL
            """
        )
    finally:
        con.unregister("_ingest_stage")


def _upsert_orders(con: duckdb.DuckDBPyConnection, batch: Batch) -> None:
    orders = list(batch.orders.values())
    table = pa.table(
        {
            "order_id": pa.array([o.order_id for o in orders], pa.string()),
            "ts": pa.array([o.ts for o in orders], pa.timestamp("us")),
            "cookie_sid_hash": pa.array([o.cookie_sid_hash for o in orders], pa.string()),
            "order_value": pa.array([o.order_value for o in orders], pa.float64()),
            "payment_method": pa.array([o.payment_method for o in orders], pa.string()),
            "request_id": pa.array([o.request_id for o in orders], pa.string()),
        }
    )
    con.register("_order_stage", table)
    try:
        con.execute(
            """
            INSERT INTO orders (order_id, ts, cookie_sid_hash, order_value, payment_method, request_id)
            SELECT order_id, ts, cookie_sid_hash, order_value, payment_method, request_id FROM _order_stage
            ON CONFLICT (order_id) DO UPDATE SET
              ts = COALESCE(orders.ts, excluded.ts),
              cookie_sid_hash = COALESCE(orders.cookie_sid_hash, excluded.cookie_sid_hash),
              order_value = COALESCE(orders.order_value, excluded.order_value),
              payment_method = COALESCE(orders.payment_method, excluded.payment_method),
              request_id = COALESCE(orders.request_id, excluded.request_id)
            """
        )
    finally:
        con.unregister("_order_stage")


def _ingest_blocks(con: duckdb.DuckDBPyConnection, path: Path, kind: str, fmt: str,
                   default_host: str) -> IngestResult:  # fmt: skip
    key = str(path.resolve())
    size = path.stat().st_size
    row = db.one(con, "SELECT last_offset FROM ingest_state WHERE source_file = ?", [key])
    offset = int(row[0]) if row else 0
    if offset > size:  # truncated or rotated in place: start over, request_id dedupe protects us
        offset = 0
    result = IngestResult(files=1)
    rules = load_rules()
    base_line: int | None = None
    with open(path, "rb") as fh:
        while True:
            fh.seek(offset)
            data = fh.read(BLOCK_BYTES)
            cut = data.rfind(b"\n")
            if cut < 0:
                break  # nothing complete yet (empty file, or a partially written last line)
            chunk = data[: cut + 1]
            lines = chunk.split(b"\n")
            lines.pop()  # trailing empty element after the final newline
            if kind == "orders":
                batch = parse_orders_block(lines)
            elif fmt == "nginx_combined":
                batch = parse_nginx_block(lines, source=key, base_offset=offset, default_host=default_host)
            else:
                batch = parse_jsonl_block(lines)

            err_rows: list[tuple[str, int, str, str, datetime]] = []
            if batch.errors:
                if base_line is None:
                    base_line = _count_newlines(path, offset)
                now = datetime.now(UTC).replace(tzinfo=None)
                err_rows = [(key, base_line + i + 1, why, raw, now) for i, why, raw in batch.errors]

            con.execute("BEGIN")
            try:
                before = db.one(con, "SELECT count(*) FROM requests")
                if batch.requests:
                    _insert_requests(con, batch.requests, path.name, rules)
                after = db.one(con, "SELECT count(*) FROM requests")
                inserted = int(after[0] - before[0]) if before and after else 0
                if batch.annotations:
                    con.executemany(
                        "INSERT OR IGNORE INTO annotations (annotation_id, ts, type, label, details_json) "
                        "VALUES (?, ?, ?, ?, ?)",
                        batch.annotations,
                    )
                if batch.orders:
                    _upsert_orders(con, batch)
                if err_rows:
                    con.executemany("INSERT INTO ingest_errors VALUES (?, ?, ?, ?, ?)", err_rows)
                new_offset = offset + len(chunk)
                con.execute(
                    "INSERT OR REPLACE INTO ingest_state (source_file, last_offset, last_ingested_at) "
                    "VALUES (?, ?, current_timestamp::TIMESTAMP)",
                    [key, new_offset],
                )
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
            result.lines += batch.lines
            result.requests_inserted += inserted
            result.duplicates += len(batch.requests) - inserted
            result.errors += len(batch.errors)
            result.annotations += len(batch.annotations)
            result.orders += len(batch.orders)
            base_line = None if base_line is None else base_line + chunk.count(b"\n")
            offset = new_offset
    result.per_file[path.name] = result.lines
    return result


def ingest_file(con: duckdb.DuckDBPyConnection, path: str | Path, fmt: str = "jsonl", *,
                kind: str = "log", default_host: str | None = None) -> IngestResult:  # fmt: skip
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r}; expected one of {FORMATS}")
    host = default_host or os.getenv("AGENTLENS_DEFAULT_HOST") or "desithreads.local"
    return _ingest_blocks(con, Path(path), kind, fmt, host)


def discover_files(path: Path, fmt: str) -> list[Path]:
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise FileNotFoundError(f"ingest source not found: {path}")
    patterns = ("*.jsonl",) if fmt == "jsonl" else ("*.log", "*.txt", "*.access")
    found = {p for pat in patterns for p in path.glob(pat) if p.name != "orders.jsonl"}
    return sorted(found)


def ingest_path(con: duckdb.DuckDBPyConnection, path: str | Path | None = None, fmt: str = "jsonl", *,
                include_orders: bool = True, default_host: str | None = None) -> IngestResult:  # fmt: skip
    """Ingest a log file or a directory of logs (plus `orders.jsonl` beside it). Safe to call repeatedly."""
    src = Path(path) if path else settings.logs_dir()
    total = IngestResult()
    for f in discover_files(src, fmt):
        total.add(ingest_file(con, f, fmt, default_host=default_host))
    if include_orders:
        seen: set[Path] = set()
        base = src if src.is_dir() else src.parent
        for cand in (base / "orders.jsonl", base.parent / "orders.jsonl"):
            if cand.exists() and cand.resolve() not in seen:
                seen.add(cand.resolve())
                orders_res = ingest_file(con, cand, "jsonl", kind="orders")
                total.orders += orders_res.orders
                total.errors += orders_res.errors
    return total
