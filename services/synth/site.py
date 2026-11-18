"""Offline model of the demo store's behaviour (PRD 8.3, docs/log-contract.md): status codes, error codes, durations,
state per client and the sub-requests a browser makes. Mirrors apps/store/lib/friction.ts; no friction labels are emitted.
"""

from __future__ import annotations

import math
import random
import re
from collections.abc import Callable
from typing import Any

from .catalog import Catalog
from .config import SynthConfig
from .model import API, ASSET, BEACON, PAGE, Client, Req, Resp

DEV_OTP = "123456"
AGENT_UA_TOKENS = [t.lower() for t in (
    "ChatGPT-User", "ChatGPT-Agent", "OAI-SearchBot", "GPTBot", "Claude-User", "Claude-SearchBot", "ClaudeBot",
    "Claude-Web", "anthropic-ai", "Perplexity-User", "PerplexityBot", "Google-Agent", "Googlebot", "Applebot",
    "Amazonbot", "meta-externalagent", "meta-externalfetcher", "CCBot", "Bytespider", "DuckAssistBot",
    "MistralAI-User", "TestSignedAgent", "python-httpx", "python-requests", "HeadlessChrome-Agent",
)]  # fmt: skip
ROBOTS_TOKENS = {t.lower() for t in (
    "GPTBot", "ChatGPT-User", "OAI-SearchBot", "ClaudeBot", "Claude-User", "Claude-SearchBot", "PerplexityBot",
    "Perplexity-User", "Google-Extended", "Applebot-Extended", "CCBot", "Bytespider", "meta-externalagent",
    "TestSignedAgent",
)}  # fmt: skip
_BOT_WALL_EXEMPT = re.compile(r"^/(admin|api/admin|robots\.txt|\.well-known/)")
_ASSET_EXT = re.compile(r"\.(?:js|mjs|css|map|svg|png|jpe?g|gif|webp|avif|ico|woff2?|ttf|otf)$", re.I)
_STRICT_PHONE = re.compile(r"^\+91 \d{5} \d{5}$")
_LENIENT_CHARS = re.compile(r"^[+\d\s\-()]+$")
_PDP = re.compile(r"^/p/([^/]+)/?$")
_VARIANTS = re.compile(r"^/api/products/([^/]+)/variants$")


def is_asset_path(p: str) -> bool:
    return p.startswith(("/_next/", "/img/")) or p == "/favicon.ico" or bool(_ASSET_EXT.search(p))


def phone_valid(strict: bool, phone: Any) -> bool:
    if not isinstance(phone, str):
        return False
    if strict:
        return bool(_STRICT_PHONE.match(phone))
    if not _LENIENT_CHARS.match(phone):
        return False
    return bool(re.match(r"^(91)?[6-9]\d{9}$", re.sub(r"\D", "", phone)))


class SiteSim:
    def __init__(self, cfg: SynthConfig, catalog: Catalog, toggles_at: Callable[[float], dict[str, bool]],
                 live: bool = False) -> None:  # fmt: skip
        self.live = live  # live mode only emits asset URLs the real store serves
        self.cfg = cfg
        self.cat = catalog
        self.toggles_at = toggles_at
        n = cfg.raw["noise"]
        self.noise = n
        d = n["duration_ms"]
        self._dur = {
            PAGE: (math.log(d["page_median"]), d["page_sigma"]),
            API: (math.log(d["api_median"]), d["api_sigma"]),
            ASSET: (math.log(d["asset_median"]), d["asset_sigma"]),
            BEACON: (math.log(8), 0.3),
        }

    # -- helpers ---------------------------------------------------------------------------------------------
    def _duration(self, rng: random.Random, kind: str) -> int:
        mu, sigma = self._dur[kind]
        return max(1, int(rng.lognormvariate(mu, sigma)))

    def _err(self, rng: random.Random, kind: str, status: int, code: str, **data: Any) -> Resp:
        return Resp(status, code, dict(data), self._duration(rng, kind), rng.randrange(60, 140), {"error_code": code})

    # -- request handling ------------------------------------------------------------------------------------
    def respond(self, client: Client, req: Req, ts: float) -> Resp:
        t = self.toggles_at(ts)
        rng = client.rng
        path = req.path
        asset = req.kind == ASSET or is_asset_path(path)
        ua_l = client.ua.lower()

        if t["F01"] and not asset and not _BOT_WALL_EXEMPT.match(path):
            if "mozilla" not in ua_l or any(tok in ua_l for tok in AGENT_UA_TOKENS):
                return Resp(403, "BOT_CHALLENGE", {}, self._duration(rng, API), 700, {"error_code": "BOT_CHALLENGE"})

        gate_exempt = asset or _BOT_WALL_EXEMPT.match(path) is not None or path == "/api/beacon"
        extra_ms = 0
        if not gate_exempt:
            if t["F12"]:
                hits = client.state.hits
                while hits and ts - hits[0] >= 60:
                    hits.popleft()
                if len(hits) >= 20:
                    retry = max(1, math.ceil(hits[0] + 60 - ts))
                    resp = self._err(rng, API, 429, "RATE_LIMITED", retry_after=retry)
                    return resp
                hits.append(ts)
            if t["F13"] and _PDP.match(path):
                extra_ms = 6000 + rng.randrange(0, 3001)

        resp = self._route(client, req, t, rng)
        resp.duration_ms += extra_ms
        if req.kind == PAGE and resp.status == 200 and rng.random() < self.noise["p_server_error"]:
            return Resp(500, None, {}, resp.duration_ms + 20, 1200, {})
        if req.kind == API and resp.status < 400 and path != "/api/beacon" and rng.random() < self.noise["p_flaky_api_retry"]:
            return self._err(rng, API, 503, "UPSTREAM_ERROR")
        return resp

    def _route(self, client: Client, req: Req, t: dict[str, bool], rng: random.Random) -> Resp:
        path, method, st = req.path, req.method, client.state
        kind = req.kind
        if kind == BEACON or path == "/api/beacon":
            return Resp(204, None, {}, self._duration(rng, BEACON), 0, {})
        if kind == ASSET:
            return Resp(200, None, {}, self._duration(rng, ASSET), rng.randrange(2_000, 180_000), {})
        if path == "/robots.txt":
            token = str(client.ua_entry.get("robots") or client.spec.get("agent_name") or "").lower()
            blocked = bool(t["F14"] and (token in ROBOTS_TOKENS or any(tk in client.ua.lower() for tk in ROBOTS_TOKENS)))
            return Resp(200, None, {"disallow_pdp": blocked}, self._duration(rng, PAGE) // 3 + 1, 160 + 700 * blocked, {})
        if path == "/api/serviceability":
            pin = dict(p.split("=", 1) for p in req.query.split("&") if "=" in p).get("pincode", "")
            if not re.match(r"^[1-9]\d{5}$", pin) or pin.startswith("9"):
                return self._err(rng, API, 422, "PINCODE_UNSERVICEABLE", serviceable=False)
            st.pincode_ok = True
            return Resp(200, None, {"serviceable": True, "eta_days": 2 + int(pin[-2:]) % 4}, self._duration(rng, API), 96,
                        {"serviceable": True})  # fmt: skip
        if path == "/api/cart" and method == "POST":
            return self._cart_add(client, req, t, rng)
        if path == "/api/cart":
            return Resp(200, None, {"items": st.cart}, self._duration(rng, API), 180, {})
        if path == "/api/otp/send":
            return Resp(200, None, {"sent": True}, self._duration(rng, API), 40, {})
        if path == "/api/otp/verify":
            body = req.body or {}
            if str(body.get("otp", "")) != DEV_OTP:
                return self._err(rng, API, 400, "OTP_INVALID")
            if body.get("purpose") == "cod":
                st.cod_otp_verified = True
            else:
                st.otp_verified = True
            return Resp(200, None, {"verified": True}, self._duration(rng, API), 20, {})
        if path == "/api/captcha":
            st.captcha_answer = "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(5))
            return Resp(200, None, {"answer": st.captcha_answer}, self._duration(rng, API), 2400, {})
        if path == "/api/checkout" and method == "POST":
            return self._checkout(client, req, t, rng)
        m = _VARIANTS.match(path)
        if m:
            return self._variants(m.group(1), req, t, rng)

        # HTML pages
        meta: dict[str, Any] = {}
        data: dict[str, Any] = {}
        status = 200
        pm = _PDP.match(path)
        if pm:
            p = self.cat.by_slug(pm.group(1))
            if p is None:
                status = 404
            else:
                meta["product_id"] = p["id"]
                data = {"product_id": p["id"], "price": p["price"]}
        return Resp(status, None, data, self._duration(rng, PAGE), rng.randrange(18_000, 64_000), meta)

    def _variants(self, product_id: str, req: Req, t: dict[str, bool], rng: random.Random) -> Resp:
        p = self.cat.get(product_id)
        if p is None:
            return self._err(rng, API, 404, "PRODUCT_NOT_FOUND")
        q = dict(x.split("=", 1) for x in req.query.split("&") if "=" in x)
        size = q.get("size", "").replace("+", " ").lower()
        colour = q.get("colour", "").lower()
        chosen = [v for v in p["variants"] if (not size or v["size"].lower() == size) and (not colour or v["colour"].lower() == colour)]
        if chosen and all(v["stock"] <= 0 for v in chosen):
            if t["F16"]:
                return self._err(rng, API, 409, "OUT_OF_STOCK")
            alts = sorted({v["size"] for v in p["variants"] if v["stock"] > 0})
            return Resp(200, None, {"in_stock": False, "alternatives": alts}, self._duration(rng, API), 240, {})
        return Resp(200, None, {"in_stock": True}, self._duration(rng, API), 120, {})

    def _cart_add(self, client: Client, req: Req, t: dict[str, bool], rng: random.Random) -> Resp:
        st = client.state
        if t["F05"] and not st.pincode_ok:
            return self._err(rng, API, 409, "PINCODE_REQUIRED")
        if t["F06"] and not st.otp_verified:
            return self._err(rng, API, 401, "AUTH_REQUIRED", redirect="/login")
        body = req.body or {}
        p = self.cat.get(str(body.get("product_id", "")))
        if p is None:
            return self._err(rng, API, 404, "PRODUCT_NOT_FOUND")
        size, colour = str(body.get("size", "")).lower(), str(body.get("colour", "")).lower()
        matches = [v for v in p["variants"] if (not size or v["size"].lower() == size) and (not colour or v["colour"].lower() == colour)]
        if len(matches) != 1:
            return self._err(rng, API, 422, "VARIANT_REQUIRED")
        qty = int(body.get("qty", 1) or 1)
        if matches[0]["stock"] < qty:
            return self._err(rng, API, 409, "OUT_OF_STOCK")
        price = p["cart_price"] if t["F11"] and p.get("price_mismatch") and p.get("cart_price") else p["price"]
        st.cart.append({"product_id": p["id"], "qty": qty, "unit_price": price})
        value = sum(i["unit_price"] * i["qty"] for i in st.cart)
        meta = {"product_id": p["id"], "unit_price": price, "qty": qty, "cart_value": value}
        return Resp(201, None, dict(meta), self._duration(rng, API), 110, meta)

    def _checkout(self, client: Client, req: Req, t: dict[str, bool], rng: random.Random) -> Resp:
        st = client.state
        body = req.body or {}
        if not st.cart:
            return self._err(rng, API, 409, "CART_EMPTY")
        solved = st.captcha_answer is not None and str(body.get("captcha_answer", "")).upper() == st.captcha_answer
        if t["F02"] and not solved:
            return self._err(rng, API, 403, "CAPTCHA_REQUIRED")
        if not phone_valid(t["F10"], body.get("phone")):
            return self._err(rng, API, 422, "PHONE_FORMAT")
        method = str(body.get("payment_method", "")).upper()
        if method not in ("COD", "UPI", "CARD"):
            return self._err(rng, API, 422, "FIELD_REQUIRED")
        cod_ok = st.cod_otp_verified or str(body.get("cod_otp", "")) == DEV_OTP
        if t["F15"] and method == "COD" and not cod_ok:
            return self._err(rng, API, 409, "COD_OTP_REQUIRED")
        order_id = f"DT-{rng.getrandbits(32):08X}"
        value = sum(i["unit_price"] * i["qty"] for i in st.cart)
        st.cart, st.captcha_answer, st.cod_otp_verified = [], None, False
        data = {"order_id": order_id, "cart_value": value, "payment_method": method}
        return Resp(201, None, dict(data), self._duration(rng, API) + 40, 150, dict(data))

    # -- browser sub-requests --------------------------------------------------------------------------------
    def page_extras(self, client: Client, req: Req, resp: Resp, t: dict[str, bool]) -> list[tuple[float, Req]]:
        """Requests a JS-running browser fires after a page loads: assets, the beacon, the captcha challenge."""
        if resp.status != 200 or not client.js:
            return []
        rng = client.rng
        out: list[tuple[float, Req]] = []
        first = client.pages_seen <= 1
        if client.assets and not client.cached_assets:
            n = rng.randrange(6, 11) if first else rng.randrange(2, 5)
            for i in range(n):
                if first and i < 4 and not self.live:
                    path = ("/_next/static/css/app.css", "/_next/static/chunks/main.js", "/_next/static/chunks/app.js",
                            "/favicon.ico")[i]  # fmt: skip
                else:
                    path = f"/img/p/{self.cat.products[rng.randrange(len(self.cat.products))]['slug']}-{1 + rng.randrange(3)}.svg"
                out.append((0.03 + rng.random() * 0.6, Req("GET", path, kind=ASSET, referer=req.path)))
        if client.beacon:
            out.append((0.25 + rng.random() * 1.2, Req("POST", "/api/beacon", kind=BEACON, referer=req.path)))
        out.sort(key=lambda x: x[0])
        return out
