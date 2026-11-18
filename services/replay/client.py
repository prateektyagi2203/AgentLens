"""HTTP client for the replay agent: allow-list, robots.txt, pacing, declared UA, optional Web Bot Auth signing.

Every request goes through `ReplayClient.request`, which refuses hosts outside the allow-list *before* any I/O (also for
redirect targets), honours robots.txt for the AgentLens-Replay token and spaces requests by `step_pause_s`.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from .config import UA_TOKEN, ReplayConfig, RobotsDisallowed

MAX_BODY = 2_000_000
MAX_REDIRECTS = 3


class BudgetExceeded(RuntimeError):
    """The replay hit its hard request / time budget."""


@dataclass
class HttpResult:
    method: str
    url: str
    status: int
    headers: dict[str, str]
    text: str
    duration_ms: int
    error_code: str | None = None
    _json: Any = field(default=None, repr=False)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 400

    def json(self) -> Any:
        if self._json is None:
            try:
                self._json = json.loads(self.text)
            except ValueError:
                self._json = {}
        return self._json

    @property
    def path(self) -> str:
        parts = urlsplit(self.url)
        return parts.path + (f"?{parts.query}" if parts.query else "")


class ReplayClient:
    def __init__(
        self, cfg: ReplayConfig, base_url: str | None = None, *, transport: httpx.BaseTransport | None = None,
        pause_s: float | None = None, sign: bool | None = None, sleep: Callable[[float], None] = time.sleep,
        max_requests: int | None = None, deadline: float | None = None,
    ) -> None:  # fmt: skip
        self.cfg = cfg
        self.base_url = (base_url or cfg.base_url).rstrip("/")
        cfg.allow_list.check(self.base_url)
        self.pause_s = cfg.step_pause_s if pause_s is None else pause_s
        self.sleep = sleep
        self.max_requests = max_requests
        self.deadline = deadline
        self.network_log: list[dict[str, Any]] = []
        self.robots_text: str | None = None
        self.robots_result: HttpResult | None = None
        self._robots: RobotFileParser | None = None
        self._last_end: float | None = None
        self._count = 0
        self.signed = cfg.sign_requests if sign is None else sign
        self._signer: Any = None
        self._http = httpx.Client(timeout=cfg.request_timeout_s, follow_redirects=False, transport=transport)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> ReplayClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def request_count(self) -> int:
        return self._count

    @property
    def cookies(self) -> httpx.Cookies:
        return self._http.cookies

    def url(self, path_or_url: str) -> str:
        return urljoin(self.base_url + "/", path_or_url)

    def _sign_headers(self, method: str, url: str) -> dict[str, str]:
        from agentlens.synth.signer import Signer

        if self._signer is None:
            self._signer = Signer(origin="https://agents.desithreads.test")
        parts = urlsplit(url)
        authority = parts.netloc
        return self._signer.sign(method, authority, parts.path or "/", parts.query, int(time.time()), scheme=parts.scheme).as_dict()

    def _pace(self) -> None:
        if self._last_end is not None and self.pause_s > 0:
            wait = self.pause_s - (time.monotonic() - self._last_end)
            if wait > 0:
                self.sleep(wait)

    def ensure_robots(self) -> RobotFileParser:
        if self._robots is None:
            res = self._send("GET", self.url("/robots.txt"), None, None, None, None)
            self.robots_result = res
            parser = RobotFileParser()
            self.robots_text = res.text if res.status == 200 else ""
            parser.parse(self.robots_text.splitlines())
            self._robots = parser
        return self._robots

    def robots_allows(self, url: str, token: str = UA_TOKEN) -> bool:
        return self.ensure_robots().can_fetch(token, self.url(url))

    def request(
        self, method: str, path_or_url: str, *, json_body: Any = None, params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None, user_agent: str | None = None, check_robots: bool = True,
    ) -> HttpResult:  # fmt: skip
        url = self.url(path_or_url)
        self.cfg.allow_list.check(url)
        if check_robots and self.cfg.respect_robots and urlsplit(url).path != "/robots.txt":
            if not self.robots_allows(url):
                raise RobotsDisallowed(f"robots.txt disallows {urlsplit(url).path} for {UA_TOKEN}")
        return self._send(method.upper(), url, json_body, params, headers, user_agent)

    def _send(
        self, method: str, url: str, json_body: Any, params: dict[str, Any] | None, headers: dict[str, str] | None,
        user_agent: str | None,
    ) -> HttpResult:  # fmt: skip
        if self.max_requests is not None and self._count >= self.max_requests:
            raise BudgetExceeded(f"request budget of {self.max_requests} reached")
        if self.deadline is not None and time.monotonic() > self.deadline:
            raise BudgetExceeded("time budget reached")
        self._pace()
        for _hop in range(MAX_REDIRECTS + 1):
            self.cfg.allow_list.check(url)
            h = {"User-Agent": user_agent or self.cfg.user_agent, "Accept": "text/html,application/json;q=0.9,*/*;q=0.5"}
            if self.signed and user_agent is None:
                h.update(self._sign_headers(method, url if not params else str(httpx.URL(url, params=params))))
            h.update(headers or {})
            t0 = time.perf_counter()
            ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            self._count += 1
            try:
                resp = self._http.request(method, url, json=json_body, params=params, headers=h)
            except httpx.HTTPError as exc:
                self.network_log.append({"ts": ts, "method": method, "url": url, "status": 0,
                                         "duration_ms": int((time.perf_counter() - t0) * 1000), "error_code": type(exc).__name__})  # fmt: skip
                self._last_end = time.monotonic()
                raise
            ms = int((time.perf_counter() - t0) * 1000)
            self._last_end = time.monotonic()
            text = resp.text[:MAX_BODY]
            res = HttpResult(method, str(resp.url), resp.status_code, dict(resp.headers), text, ms)
            res.error_code = _error_code(res)
            self.network_log.append({"ts": ts, "method": method, "url": str(resp.url), "status": resp.status_code,
                                     "duration_ms": ms, "error_code": res.error_code})  # fmt: skip
            if resp.status_code in (301, 302, 303, 307, 308) and "location" in resp.headers:
                url = urljoin(url, resp.headers["location"])
                if resp.status_code in (301, 302, 303):
                    method, json_body, params = "GET", None, None
                continue
            return res
        return res


def _error_code(res: HttpResult) -> str | None:
    if res.headers.get("content-type", "").startswith("application/json"):
        code = res.json().get("error_code") if isinstance(res.json(), dict) else None
        if code:
            return str(code)
    if res.status == 403 and "Checking your browser" in res.text[:2000]:
        return "BOT_CHALLENGE"
    if res.status == 429:
        return "RATE_LIMITED"
    return None
