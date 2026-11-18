"""Line parsers: native JSONL (PRD 9.2) and nginx combined (optionally with signature headers) -> normalised tuples."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import orjson

from .. import settings
from ..identify.signatures import parse_signature_agent

REQ_COLS = (
    "request_id", "ts", "method", "host", "path", "query", "status", "bytes_out", "duration_ms",
    "ip_hash", "ip_prefix", "user_agent", "referer", "accept", "accept_language", "sec_ch_ua",
    "sec_fetch_site", "sec_fetch_mode", "sec_fetch_dest", "signature", "signature_input",
    "signature_agent", "signature_agent_origin", "cookie_sid_hash", "is_asset", "event_type", "error_code",
        "unit_price", "product_id",
)  # fmt: skip

# `meta` keys we are willing to read. Anything else in meta is ignored, never stored.
ORDER_META = ("order_id", "cart_value", "payment_method")

_UTC = UTC


@dataclass
class OrderRow:
    order_id: str
    ts: datetime | None = None
    cookie_sid_hash: str | None = None
    order_value: float | None = None
    payment_method: str | None = None
    request_id: str | None = None


@dataclass
class Batch:
    requests: list[tuple[Any, ...]] = field(default_factory=list)
    orders: dict[str, OrderRow] = field(default_factory=dict)
    annotations: list[tuple[str, datetime, str, str, str]] = field(default_factory=list)
    errors: list[tuple[int, str, str]] = field(default_factory=list)  # (index within block, reason, raw line)
    lines: int = 0

    def add_order(self, o: OrderRow) -> None:
        cur = self.orders.get(o.order_id)
        if cur is None:
            self.orders[o.order_id] = o
            return
        for name in ("ts", "cookie_sid_hash", "order_value", "payment_method", "request_id"):
            if getattr(cur, name) is None:
                setattr(cur, name, getattr(o, name))


def parse_ts(value: Any) -> datetime:
    """ISO-8601 -> naive UTC datetime (microsecond precision)."""
    if not isinstance(value, str):
        raise ValueError("ts must be an ISO-8601 string")
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is not None:
        dt = dt.astimezone(_UTC).replace(tzinfo=None)
    return dt


def _s(v: Any) -> str | None:
    if v is None or v == "":
        return None
    return v if isinstance(v, str) else str(v)


def _int(v: Any) -> int | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _num(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _config_change_annotation(ts: datetime, meta: dict[str, Any]) -> tuple[str, datetime, str, str, str]:
    raw_toggles, raw_changed = meta.get("toggles"), meta.get("changed")
    toggles: dict[str, Any] = raw_toggles if isinstance(raw_toggles, dict) else {}
    changed: list[Any] = raw_changed if isinstance(raw_changed, list) else []
    label = "; ".join(f"{f} {'on' if toggles.get(f) else 'off'}" for f in changed) or "config change"
    details = json.dumps({"toggles": toggles, "changed": changed}, sort_keys=True)
    digest = hashlib.sha1(f"{ts.isoformat()}|{details}".encode()).hexdigest()[:16]
    return f"ann-{digest}", ts, "config_change", label, details


def parse_jsonl_block(lines: list[bytes]) -> Batch:
    batch = Batch(lines=len(lines))
    reqs = batch.requests
    loads = orjson.loads
    for idx, raw in enumerate(lines):
        if not raw.strip():
            batch.lines -= 1
            continue
        try:
            rec = loads(raw)
            if not isinstance(rec, dict):
                raise ValueError("line is not a JSON object")
            ts = parse_ts(rec.get("ts"))
            event = rec.get("event_type") or "request"
            meta = rec.get("meta")
            if not isinstance(meta, dict):
                meta = {}
            if event == "config_change":
                batch.annotations.append(_config_change_annotation(ts, meta))
                continue
            if event == "order":
                oid = _s(meta.get("order_id"))
                if not oid:
                    raise ValueError("order event without meta.order_id")
                batch.add_order(
                    OrderRow(oid, ts, _s(rec.get("cookie_sid_hash")), _num(meta.get("cart_value")),
                             _s(meta.get("payment_method")), None)
                )  # fmt: skip
                continue
            rid = _s(rec.get("request_id"))
            method = _s(rec.get("method"))
            path = _s(rec.get("path"))
            if not rid or not method or not path:
                raise ValueError("missing request_id, method or path")
            status = rec.get("status")
            status = int(status) if status is not None else None
            if event not in ("request", "beacon"):
                raise ValueError(f"unknown event_type {event!r}")
            sig_agent = _s(rec.get("signature_agent"))
            reqs.append(
                (
                    rid, ts, method.upper(), _s(rec.get("host")), path, rec.get("query") or "", status,
                    _int(rec.get("bytes_out")), _int(rec.get("duration_ms")), _s(rec.get("ip_hash")), _s(rec.get("ip_prefix")),
                    _s(rec.get("user_agent")), _s(rec.get("referer")), _s(rec.get("accept")),
                    _s(rec.get("accept_language")), _s(rec.get("sec_ch_ua")), _s(rec.get("sec_fetch_site")),
                    _s(rec.get("sec_fetch_mode")), _s(rec.get("sec_fetch_dest")), _s(rec.get("signature")),
                    _s(rec.get("signature_input")), sig_agent,
                    parse_signature_agent(sig_agent) if sig_agent else None,
                    _s(rec.get("cookie_sid_hash")), bool(rec.get("is_asset")), event, _s(meta.get("error_code")),
                                        _num(meta.get("unit_price")), _s(meta.get("product_id")),                )
            )  # fmt: skip
            if method == "POST" and path == "/api/checkout" and status == 201 and meta.get("order_id"):
                batch.add_order(
                    OrderRow(str(meta["order_id"]), ts, _s(rec.get("cookie_sid_hash")), _num(meta.get("cart_value")),
                             _s(meta.get("payment_method")), rid)
                )  # fmt: skip
        except (ValueError, TypeError, KeyError) as exc:
            batch.errors.append((idx, f"{type(exc).__name__}: {exc}"[:300], raw.decode("utf-8", "replace")[:2000]))
    return batch


def parse_orders_block(lines: list[bytes]) -> Batch:
    """`<data>/orders.jsonl`: {order_id, session_cookie_id, cart_value, ts, payment_method}."""
    batch = Batch(lines=len(lines))
    for idx, raw in enumerate(lines):
        if not raw.strip():
            batch.lines -= 1
            continue
        try:
            rec = orjson.loads(raw)
            oid = _s(rec.get("order_id")) if isinstance(rec, dict) else None
            if not oid:
                raise ValueError("missing order_id")
            batch.add_order(
                OrderRow(oid, parse_ts(rec.get("ts")), _s(rec.get("session_cookie_id") or rec.get("cookie_sid_hash")),
                         _num(rec.get("cart_value")), _s(rec.get("payment_method")), None)
            )  # fmt: skip
        except (ValueError, TypeError, AttributeError) as exc:
            batch.errors.append((idx, f"{type(exc).__name__}: {exc}"[:300], raw.decode("utf-8", "replace")[:2000]))
    return batch


# ---- nginx combined -------------------------------------------------------------------------------------------

_Q = r'"((?:[^"\\]|\\.)*)"'
# $remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent "$http_referer" "$http_user_agent"
# optional: "$http_signature" "$http_signature_input" "$http_signature_agent" then optional $request_time (seconds)
_NGINX = re.compile(
    rf"^(\S+) \S+ \S+ \[([^\]]+)\] {_Q} (\d{{3}}) (\d+|-)(?: {_Q} {_Q})?(?: {_Q} {_Q} {_Q})?(?: ([\d.]+))?\s*$"
)
_MONTHS = {m: i + 1 for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}
_TIME_LOCAL = re.compile(r"(\d{2})/(\w{3})/(\d{4}):(\d{2}):(\d{2}):(\d{2}) ([+-])(\d{2})(\d{2})")
_HEX_ESC = re.compile(r"\\x([0-9A-Fa-f]{2})")
_ASSET_EXT = re.compile(r"\.(js|css|png|jpe?g|svg|webp|ico|woff2?)$")


def _unescape(v: str | None) -> str | None:
    if v is None or v == "-" or v == "":
        return None
    v = _HEX_ESC.sub(lambda m: chr(int(m.group(1), 16)), v)
    return v.replace('\\"', '"').replace("\\\\", "\\")


def parse_time_local(v: str) -> datetime:
    m = _TIME_LOCAL.fullmatch(v.strip())
    if not m:
        raise ValueError(f"bad $time_local {v!r}")
    day, mon, year, hh, mm, ss, sign, oh, om = m.groups()
    local = datetime(int(year), _MONTHS[mon], int(day), int(hh), int(mm), int(ss))
    offset = timedelta(hours=int(oh), minutes=int(om))
    return local - offset if sign == "+" else local + offset


@lru_cache(maxsize=65536)
def _hash_ip(ip: str) -> tuple[str, str | None]:
    digest = hashlib.sha256((settings.ip_salt() + ip).encode()).hexdigest()
    try:
        addr = ipaddress.ip_address(ip)
        prefix = ipaddress.ip_network(f"{ip}/{24 if addr.version == 4 else 48}", strict=False)
        return digest, str(prefix)
    except ValueError:
        return digest, None


def parse_nginx_block(lines: list[bytes], *, source: str, base_offset: int, default_host: str) -> Batch:
    batch = Batch(lines=len(lines))
    pos = base_offset
    for idx, raw in enumerate(lines):
        line_start = pos
        pos += len(raw) + 1
        text = raw.decode("utf-8", "replace").strip()
        if not text:
            batch.lines -= 1
            continue
        try:
            m = _NGINX.match(text)
            if not m:
                raise ValueError("line does not match nginx combined format")
            ip, tl, request, status, nbytes, ref, ua, sig, sig_in, sig_agent, rtime = m.groups()
            parts = (_unescape(request) or "").split(" ")
            if len(parts) < 2:
                raise ValueError("bad request line")
            method, target = parts[0].upper(), parts[1]
            path, _, query = target.partition("?")
            ip_hash, ip_prefix = _hash_ip(ip)
            rid = hashlib.sha1(f"{source}:{line_start}".encode()).hexdigest()[:32]
            is_asset = bool(_ASSET_EXT.search(path)) or path.startswith(("/_next/", "/static/", "/img/"))
            event = "beacon" if path.startswith("/api/beacon") else "request"
            sa = _unescape(sig_agent)
            batch.requests.append(
                (
                    rid, parse_time_local(tl), method, default_host, path, query, int(status),
                    None if nbytes == "-" else int(nbytes), int(float(rtime) * 1000) if rtime else None,
                    ip_hash, ip_prefix, _unescape(ua), _unescape(ref), None, None, None, None, None, None,
                    _unescape(sig), _unescape(sig_in), sa, parse_signature_agent(sa) if sa else None, None,
                    is_asset, event, None, None, None,
                )
            )  # fmt: skip
        except (ValueError, KeyError) as exc:
            batch.errors.append((idx, f"{type(exc).__name__}: {exc}"[:300], text[:2000]))
    return batch
