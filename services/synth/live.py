"""Live synthetic traffic against the running store (PRD 17.1): httpx for fetchers and humans, Playwright for a sample of
browsing agents. Requests carry `X-Synth-Session` (the store records it only when AGENTLENS_SYNTH_MODE=1) and
`X-Forwarded-For` (the synthetic client IP, which the store hashes).

Think times are divided by `speed` so that a few thousand sessions finish in minutes rather than days.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from http.cookiejar import DefaultCookiePolicy
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from agentlens import settings

from .catalog import Catalog
from .config import FRICTION_IDS, SynthConfig
from .groundtruth import GroundTruthWriter
from .journeys import Ctx, run_journey
from .model import API, ASSET, BEACON, PAGE, Client, Outcome, Req, Resp
from .personas import build_signer, make_client
from .signer import Signer
from .site import SiteSim

FRICTION_FILE = settings.REPO_ROOT / "apps" / "store" / "config" / "friction.json"
_COOKIE = re.compile(r"dt_sid=([^;]+)")
_PAGE_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"


def parse_rate(value: str | float) -> float:
    if isinstance(value, int | float):
        return float(value)
    return float(value.strip().lower().removesuffix("/s").removesuffix("/sec"))


def friction_reader(cfg: SynthConfig, path: Path = FRICTION_FILE) -> Callable[[float], dict[str, bool]]:
    """Toggle accessor for journeys in live mode: the store's own friction.json (same machine), else the Before state."""
    fallback = cfg.state("before")
    cache: dict[str, Any] = {"mtime": None, "toggles": fallback}

    def read(_ts: float) -> dict[str, bool]:
        try:
            mtime = path.stat().st_mtime
            if mtime != cache["mtime"]:
                raw = json.loads(path.read_text(encoding="utf-8")).get("toggles", {})
                cache["toggles"] = {f: bool(raw.get(f, False)) for f in FRICTION_IDS}
                cache["mtime"] = mtime
        except (OSError, ValueError):
            pass
        toggles: dict[str, bool] = cache["toggles"]
        return toggles

    return read


@dataclass
class LiveResult:
    run_id: str
    sessions: int
    requests: int
    seconds: float
    ground_truth: Path | None
    outcomes: list[Outcome] = field(default_factory=list)
    errors: int = 0
    browser_sessions: int = 0


class LiveRunner:
    def __init__(self, store_url: str, cfg: SynthConfig, catalog: Catalog, *, seed: int = 1, speed: float = 10.0,
                 toggles_fn: Callable[[float], dict[str, bool]] | None = None, signer: Signer | None = None,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:  # fmt: skip
        self.store_url = store_url.rstrip("/")
        self.authority = urlsplit(self.store_url).netloc
        self.cfg, self.cat, self.seed, self.speed = cfg, catalog, seed, max(speed, 0.001)
        self.toggles_fn = toggles_fn or friction_reader(cfg)
        self.signer = signer or build_signer(cfg.raw)
        self.site = SiteSim(cfg, catalog, self.toggles_fn, live=True)
        self.http = httpx.AsyncClient(base_url=self.store_url, transport=transport, timeout=30.0, follow_redirects=False)
        # Each synthetic client manages its own cookie (below); the shared jar would leak one session's cookie into others.
        self.http.cookies.jar.set_policy(DefaultCookiePolicy(allowed_domains=[]))
        self.requests = 0
        self.errors = 0
        self.cookies: dict[str, str] = {}

    async def aclose(self) -> None:
        await self.http.aclose()

    # -- transport ---------------------------------------------------------------------------------------------
    def _headers(self, c: Client, req: Req) -> dict[str, str]:
        h = {"User-Agent": c.ua, "X-Forwarded-For": c.ip, "X-Synth-Session": c.synth_session_id}
        if req.kind == PAGE:
            h["Accept"] = _PAGE_ACCEPT if c.headers["html"] else "*/*"
        elif req.kind == ASSET:
            h["Accept"] = "image/avif,image/webp,image/*,*/*;q=0.8"
        else:
            h["Accept"] = "application/json, text/plain, */*" if c.js else "*/*"
        if c.headers["accept_language"]:
            h["Accept-Language"] = c.headers["accept_language"]
        if c.js and c.headers["sec_ch_ua"]:
            h["Sec-CH-UA"] = c.headers["sec_ch_ua"]
        if c.headers["sec_fetch"]:
            h["Sec-Fetch-Site"] = "same-origin" if req.referer else "none"
            h["Sec-Fetch-Mode"] = "navigate" if req.kind == PAGE else "cors"
            h["Sec-Fetch-Dest"] = "document" if req.kind == PAGE else "empty"
        if req.referer:
            h["Referer"] = f"{self.store_url}{req.referer}"
        if c.has_cookie and c.keeps_cookies and c.cookie_uuid in self.cookies:
            h["Cookie"] = f"dt_sid={self.cookies[c.cookie_uuid]}"
        if c.signer_mode and req.kind in (PAGE, API) and req.sign:
            created = int(time.time()) - random.randrange(0, 3)
            signed = self.signer.sign(req.method, self.authority, req.path, req.query, created, scheme="http", mode=c.signer_mode)
            h["Signature"], h["Signature-Input"], h["Signature-Agent"] = signed.signature, signed.signature_input, signed.signature_agent
        return h

    async def send(self, c: Client, req: Req) -> Resp:
        url = req.path + (f"?{req.query}" if req.query else "")
        started = time.perf_counter()
        self.requests += 1
        try:
            r = await self.http.request(req.method, url, headers=self._headers(c, req),
                                        json=req.body if req.body is not None else None)  # fmt: skip
        except httpx.HTTPError:
            self.errors += 1
            return Resp(599, "NETWORK_ERROR", {}, int((time.perf_counter() - started) * 1000))
        ms = int((time.perf_counter() - started) * 1000)
        if c.keeps_cookies:
            for value in r.headers.get_list("set-cookie"):
                m = _COOKIE.search(value)
                if m:
                    self.cookies[c.cookie_uuid] = m.group(1)
                    c.has_cookie = True
        return self._to_resp(req, r, ms)

    @staticmethod
    def _to_resp(req: Req, r: httpx.Response, ms: int) -> Resp:
        data: dict[str, Any] = {}
        code: str | None = None
        ctype = r.headers.get("content-type", "")
        if "json" in ctype:
            try:
                parsed = r.json()
                data = parsed if isinstance(parsed, dict) else {}
                code = data.get("error_code")
            except ValueError:
                pass
        elif req.path == "/robots.txt":
            data = {"disallow_pdp": bool(re.search(r"(?im)^disallow:\s*/(p|checkout)", r.text))}
        if r.status_code == 429:
            data.setdefault("retry_after", int(r.headers.get("retry-after", "60") or 60))
            code = code or "RATE_LIMITED"
        if r.status_code == 403 and code is None and req.kind != ASSET:
            code = "BOT_CHALLENGE"
        return Resp(r.status_code, code, data, ms, len(r.content))

    # -- sessions ----------------------------------------------------------------------------------------------
    async def run_session(self, index: int, persona: str) -> tuple[Outcome, Client]:
        spec = self.cfg.personas[persona]
        rng = random.Random(self.seed * 1_000_003 + index)
        client = make_client(persona, spec, rng, f"syn-{self.seed:x}-L{index:07x}")
        out = Outcome(task="")
        ctx = Ctx(client, self.cat, self.cfg.raw, self.toggles_fn, out)
        await drive(ctx, run_journey(ctx), lambda r: self.send(client, r), self.site, self.speed)
        return out, client


async def drive(ctx: Ctx, gen: Any, send: Callable[[Req], Awaitable[Resp]], site: SiteSim | None, speed: float,
                extras: bool = True) -> None:  # fmt: skip
    client = ctx.c
    try:
        req = next(gen)
        while True:
            await asyncio.sleep(req.think / speed)
            if req.kind == PAGE:
                client.pages_seen += 1
            resp = await send(req)
            if extras and site is not None and req.kind == PAGE:
                for offset, extra in site.page_extras(client, req, resp, {}):
                    await asyncio.sleep(min(offset, 0.5) / speed)
                    await send(extra)
            ctx.t = time.time()
            req = gen.send(resp)
    except StopIteration:
        return


async def run_live(
    *, sessions: int, rate: str | float = "20/s", seed: int = 1, store_url: str | None = None, speed: float = 10.0,
    concurrency: int = 64, browser_share: float = 0.0, data_dir: Path | None = None, run_id: str | None = None,
    cfg: SynthConfig | None = None, transport: httpx.AsyncBaseTransport | None = None,
) -> LiveResult:  # fmt: skip
    cfg = cfg or SynthConfig.load()
    store_url = store_url or str(cfg.raw["store_url"])
    run_id = run_id or f"live-{seed}"
    runner = LiveRunner(store_url, cfg, Catalog.load(), seed=seed, speed=speed, transport=transport)
    names, shares = cfg.shares()
    rng = random.Random(seed)
    plan = [rng.choices(names, weights=shares)[0] for _ in range(sessions)]
    interval = 1.0 / parse_rate(rate)
    sem = asyncio.Semaphore(concurrency)
    gt_rows: list[dict[str, Any]] = []
    outcomes: list[Outcome] = []
    browser = BrowserDriver(runner) if browser_share > 0 else None
    browser_sessions = 0
    started = time.perf_counter()

    async def one(i: int, persona: str) -> None:
        nonlocal browser_sessions
        async with sem:
            spec = cfg.personas[persona]
            use_browser = bool(browser) and spec["behavior"] == "shopper" and random.Random(seed + i).random() < browser_share
            if use_browser and browser is not None:
                out, client = await browser.run_session(i, persona)
                browser_sessions += 1
            else:
                out, client = await runner.run_session(i, persona)
            outcomes.append(out)
            row = _gt_row(run_id, f"syn-{seed:x}-L{i:07x}", persona, spec, out, client)
            row["toggles_active"] = [f for f, on in runner.toggles_fn(time.time()).items() if on]
            gt_rows.append(row)

    try:
        tasks = []
        for i, persona in enumerate(plan):
            tasks.append(asyncio.create_task(one(i, persona)))
            await asyncio.sleep(interval)
        await asyncio.gather(*tasks)
    finally:
        await runner.aclose()
        if browser:
            await browser.close()
    gt_path = None
    if data_dir is not None:
        writer = GroundTruthWriter(data_dir / "ground_truth" / f"gt-{run_id}.jsonl")
        for row in gt_rows:
            writer.add(row)
        gt_path = writer.close()
    return LiveResult(run_id, sessions, runner.requests, time.perf_counter() - started, gt_path, outcomes, runner.errors,
                      browser_sessions)  # fmt: skip


def _gt_row(run_id: str, sid: str, persona: str, spec: dict[str, Any], out: Outcome, client: Client) -> dict[str, Any]:
    entry = client.ua_entry
    human = spec["behavior"] == "human"
    return {
        "run_id": run_id, "synthetic_session_id": sid, "persona": persona, "expected_tier": spec["tier"],
        "operator": entry.get("operator") or spec.get("operator"), "agent_name": entry.get("name") or spec.get("agent_name"),
        "agent_class": "human" if human else (entry.get("class") or spec.get("agent_class")), "task": out.task,
        "toggles_active": [], "blocker_hit": out.blocker, "stage_of_failure": out.stage_of_failure,
        "converted": out.converted,
    }  # fmt: skip


class BrowserDriver:
    """Drives browsing-agent journeys through headless Chromium (Playwright). Pages are real navigations, so the store's
    own scripts fire the beacon and load assets; API calls go through the context's request client."""

    def __init__(self, runner: LiveRunner) -> None:
        self.runner = runner
        self._pw: Any = None
        self._browser: Any = None

    async def _start(self) -> None:
        if self._browser is None:
            from playwright.async_api import async_playwright

            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(headless=True)

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            await self._pw.stop()

    async def run_session(self, index: int, persona: str) -> tuple[Outcome, Client]:
        await self._start()
        r = self.runner
        spec = r.cfg.personas[persona]
        rng = random.Random(r.seed * 1_000_003 + index)
        client = make_client(persona, spec, rng, f"syn-{r.seed:x}-L{index:07x}")
        out = Outcome(task="")
        ctx = Ctx(client, r.cat, r.cfg.raw, r.toggles_fn, out)
        context = await self._browser.new_context(
            user_agent=client.ua, base_url=r.store_url,
            extra_http_headers={"X-Forwarded-For": client.ip, "X-Synth-Session": client.synth_session_id},
        )  # fmt: skip
        page = await context.new_page()
        if client.signer_mode:
            async def sign_route(route: Any) -> None:
                req = route.request
                if req.resource_type != "document":
                    await route.continue_()
                    return
                u = urlsplit(req.url)
                s = r.signer.sign(req.method, r.authority, u.path, u.query, int(time.time()), scheme="http",
                                  mode=client.signer_mode or "valid")  # fmt: skip
                headers = {**req.headers, "signature": s.signature, "signature-input": s.signature_input,
                           "signature-agent": s.signature_agent}  # fmt: skip
                await route.continue_(headers=headers)

            await page.route("**/*", sign_route)

        async def send(req: Req) -> Resp:
            url = req.path + (f"?{req.query}" if req.query else "")
            started = time.perf_counter()
            r.requests += 1
            if req.kind == PAGE:
                response = await page.goto(url, wait_until="load")
                status = response.status if response else 599
                body = await response.text() if response and req.path == "/robots.txt" else ""
                data: dict[str, Any] = {"disallow_pdp": bool(re.search(r"(?im)^disallow:\s*/(p|checkout)", body))}
                code = "BOT_CHALLENGE" if status == 403 else None
                return Resp(status, code, data, int((time.perf_counter() - started) * 1000))
            api_resp = await context.request.fetch(url, method=req.method, data=json.dumps(req.body) if req.body else None,
                                                   headers={"content-type": "application/json"} if req.body else None)  # fmt: skip
            parsed: Any = {}
            try:
                parsed = await api_resp.json()
            except Exception:
                parsed = {}
            data = parsed if isinstance(parsed, dict) else {}
            code = data.get("error_code")
            if api_resp.status == 429:
                data.setdefault("retry_after", int(api_resp.headers.get("retry-after", "60")))
                code = code or "RATE_LIMITED"
            return Resp(api_resp.status, code, data, int((time.perf_counter() - started) * 1000))

        try:
            await drive(ctx, run_journey(ctx), send, None, r.speed, extras=False)
        finally:
            await context.close()
        return out, client


__all__ = ["BEACON", "LiveRunner", "LiveResult", "run_live", "BrowserDriver", "parse_rate", "friction_reader"]
