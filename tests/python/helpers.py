"""Shared builders for log records and database fixtures."""

from __future__ import annotations

import itertools
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
HEADLESS_UA = BROWSER_UA.replace("Chrome/", "HeadlessChrome/")
T0 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=UTC)
CREATED_TS = int(T0.timestamp())
_ids = itertools.count(1)


def iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def rec(offset_s: float = 0.0, **kw: Any) -> dict[str, Any]:
    """A native-schema request record at T0 + offset_s with browser-like defaults."""
    n = next(_ids)
    base: dict[str, Any] = {
        "ts": iso(T0 + timedelta(seconds=offset_s)),
        "request_id": f"req-{n:08d}",
        "method": "GET",
        "host": "desithreads.local",
        "path": "/",
        "query": "",
        "status": 200,
        "bytes_out": 1000,
        "duration_ms": 50,
        "ip_hash": "iphash-a",
        "ip_prefix": "10.1.2.0/24",
        "user_agent": BROWSER_UA,
        "referer": None,
        "accept": "text/html,application/xhtml+xml",
        "accept_language": "en-IN",
        "sec_ch_ua": None,
        "sec_fetch_site": "same-origin",
        "sec_fetch_mode": "navigate",
        "sec_fetch_dest": "document",
        "signature": None,
        "signature_input": None,
        "signature_agent": None,
        "cookie_sid_hash": None,
        "is_asset": False,
        "event_type": "request",
        "meta": {},
    }
    base.update(kw)
    return base


def write_jsonl(path: Path, records: list[dict[str, Any]], *, final_newline: bool = True) -> Path:
    text = "\n".join(json.dumps(r) for r in records)
    path.write_text(text + ("\n" if final_newline else ""), encoding="utf-8")
    return path


def human_visit(start: float, cookie: str, ip: str = "iphash-h", n_pages: int = 3) -> list[dict[str, Any]]:
    """A human-looking browse: pages with assets and a beacon, spaced out irregularly."""
    out: list[dict[str, Any]] = []
    t = start
    for i in range(n_pages):
        path = ["/", "/c/sneakers", "/p/some-shoe", "/cart"][i % 4]
        out.append(rec(t, path=path, cookie_sid_hash=cookie, ip_hash=ip))
        out.append(rec(t + 0.3, path="/_next/static/app.js", is_asset=True, cookie_sid_hash=cookie, ip_hash=ip,
                       accept="*/*", sec_fetch_mode="no-cors", sec_fetch_dest="script"))  # fmt: skip
        out.append(rec(t + 1.0, method="POST", path="/api/beacon", status=204, event_type="beacon",
                       cookie_sid_hash=cookie, ip_hash=ip, accept="*/*"))  # fmt: skip
        t += 17 + (i * 23) % 41
    return out
