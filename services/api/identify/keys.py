"""Key discovery for Web Bot Auth: JWKS directories fetched from the Signature-Agent origin, cached, with bundled fallbacks."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import httpx

from .. import db, settings

DIRECTORY_PATH = "/.well-known/http-message-signatures-directory"
TEST_OPERATOR_ORIGIN = "https://agents.desithreads.test"
BUNDLED_KEYS_FILE = Path(__file__).with_name("bundled_keys.json")
STORE_JWKS_FILE = settings.REPO_ROOT / "apps" / "store" / "config" / "test-operator-jwks.json"


def jwk_thumbprint(jwk: dict[str, Any]) -> str:
    """RFC 7638 SHA-256 thumbprint (base64url, no padding). Supports OKP/Ed25519, EC and RSA members."""
    kty = jwk.get("kty")
    members = {"OKP": ("crv", "kty", "x"), "EC": ("crv", "kty", "x", "y"), "RSA": ("e", "kty", "n")}.get(str(kty))
    if members is None or any(m not in jwk for m in members):
        return ""
    canonical = json.dumps({m: jwk[m] for m in members}, separators=(",", ":"))
    return base64.urlsafe_b64encode(hashlib.sha256(canonical.encode()).digest()).rstrip(b"=").decode()


@dataclass
class KeySet:
    status: str  # "ok" | "fetch_failed"
    keys: list[dict[str, Any]] = field(default_factory=list)
    origin: str | None = None
    detail: str = ""


def _http_fetch(url: str, timeout_s: float = 3.0) -> dict[str, Any]:
    resp = httpx.get(url, timeout=timeout_s, follow_redirects=True, headers={"Accept": "application/json"})
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict) or not isinstance(data.get("keys"), list):
        raise ValueError("directory is not a JWKS document")
    return data


def load_bundled_keys() -> dict[str, list[dict[str, Any]]]:
    """Package-bundled public keys plus the store's test-operator JWKS if the store generated one."""
    out: dict[str, list[dict[str, Any]]] = {}
    for path, forced_origin in ((BUNDLED_KEYS_FILE, None), (STORE_JWKS_FILE, TEST_OPERATOR_ORIGIN)):
        if not path.exists():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if forced_origin:
            doc = {forced_origin: doc}
        for origin, jwks in doc.items():
            keys = jwks.get("keys", []) if isinstance(jwks, dict) else []
            known = {jwk_thumbprint(k) for k in out.get(origin, [])}
            out.setdefault(origin, []).extend(k for k in keys if jwk_thumbprint(k) not in known)
    return out


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class KeyResolver:
    """Resolves an operator origin to its public keys. Order: fresh cache -> live fetch -> stale cache -> bundled."""

    def __init__(
        self,
        con: duckdb.DuckDBPyConnection | None = None,
        *,
        ttl_s: int = 3600,
        offline: bool = False,
        fetcher: Callable[[str], dict[str, Any]] | None = None,
        bundled: dict[str, list[dict[str, Any]]] | None = None,
        overrides: dict[str, str] | None = None,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.con = con
        self.ttl_s = ttl_s
        self.offline = offline
        self.fetcher = fetcher or _http_fetch
        self.bundled = load_bundled_keys() if bundled is None else bundled
        self.overrides = overrides or {}
        self.now = now
        self._mem: dict[str, KeySet] = {}

    def _cached_row(self, origin: str) -> tuple[datetime, list[dict[str, Any]], str] | None:
        if self.con is None:
            return None
        row = db.one(
            self.con, "SELECT fetched_at, keys_json, status FROM key_cache WHERE signature_agent = ?", [origin]
        )
        if not row:
            return None
        try:
            keys = json.loads(row[1] or "[]")
        except ValueError:
            keys = []
        return row[0], keys, row[2]

    def _store(self, origin: str, keys: list[dict[str, Any]], status: str) -> None:
        if self.con is None:
            return
        self.con.execute(
            "INSERT OR REPLACE INTO key_cache (signature_agent, fetched_at, keys_json, status) VALUES (?, ?, ?, ?)",
            [origin, self.now(), json.dumps(keys), status],
        )

    def get_keys(self, origin: str) -> KeySet:
        if origin in self._mem:
            return self._mem[origin]
        result = self._resolve(origin)
        self._mem[origin] = result
        return result

    def _resolve(self, origin: str) -> KeySet:
        cached = self._cached_row(origin)
        cached_ok = cached is not None and cached[2] == "ok"
        if cached and cached_ok and (self.now() - cached[0]).total_seconds() < self.ttl_s:
            return KeySet("ok", cached[1], origin)
        if self.offline:
            if cached and cached_ok:
                return KeySet("ok", cached[1], origin)
            if origin in self.bundled:
                return KeySet("ok", self.bundled[origin], origin)
            return KeySet("fetch_failed", origin=origin, detail="offline mode, no cached or bundled keys")
        url = self.overrides.get(origin, origin + DIRECTORY_PATH)
        try:
            doc = self.fetcher(url)
            keys = [k for k in doc.get("keys", []) if isinstance(k, dict)]
        except Exception as exc:  # network, TLS, JSON, HTTP status: all mean "could not fetch"
            if cached and cached_ok:
                return KeySet("ok", cached[1], origin)
            if origin in self.bundled:
                return KeySet("ok", self.bundled[origin], origin)
            self._store(origin, [], "fetch_failed")
            return KeySet("fetch_failed", origin=origin, detail=f"{type(exc).__name__}: {exc}"[:200])
        self._store(origin, keys, "ok")
        return KeySet("ok", keys, origin)

    def find_by_keyid(self, keyid: str) -> KeySet:
        """No Signature-Agent header: look the keyid up among every directory we already know."""
        origins = set(self.bundled) | set(self._mem)
        if self.con is not None:
            origins |= {r[0] for r in self.con.execute("SELECT signature_agent FROM key_cache").fetchall()}
        for origin in sorted(origins):
            ks = self.get_keys(origin) if self.offline or origin in self.bundled or origin in self._mem else None
            if ks is None:
                cached = self._cached_row(origin)
                ks = KeySet("ok", cached[1], origin) if cached and cached[2] == "ok" else None
            if ks and ks.status == "ok" and any(jwk_thumbprint(k) == keyid for k in ks.keys):
                return ks
        if not origins:
            return KeySet("fetch_failed", detail="no Signature-Agent header and no known key directories")
        return KeySet("ok", [], None)
