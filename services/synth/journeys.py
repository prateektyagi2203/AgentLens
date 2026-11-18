"""Client behaviour as generators: each journey yields `Req`, receives the `Resp`, and returns an `Outcome`.

The same journeys drive the offline simulator and the live (httpx / Playwright) driver. Journeys react to responses
(retry, alternative path, abandon); they consult toggles only for friction that is visible in the UI but leaves no trace in
the API (F02 captcha widget, F03, F04, F07, F08, F09), exactly what a human or agent looking at the page would see.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Generator
from dataclasses import dataclass, field, replace
from typing import Any, NoReturn
from urllib.parse import quote_plus

from .catalog import Catalog
from .model import API, ASSET, BEACON, PAGE, Client, Outcome, Req, Resp  # noqa: F401

Journey = Generator[Req, Resp, Outcome]

CODE_BLOCKER = {
    "BOT_CHALLENGE": "B01", "CAPTCHA_REQUIRED": "B02", "PINCODE_REQUIRED": "B05", "AUTH_REQUIRED": "B06",
    "OUT_OF_STOCK": "B08", "PHONE_FORMAT": "B10", "COD_OTP_REQUIRED": "B11", "RATE_LIMITED": "B12",
}  # fmt: skip
PINCODES = ("201301", "110001", "560001", "400001", "600001", "700001", "500001", "122001")
STRICT_PHONES = ("+91 98765 43210", "+91 91234 56789", "+91 99887 76655", "+91 70123 45678")
LOOSE_PHONES = ("9876543210", "98765 43210", "+91-9876543210", "09123456789", "+919123456789")
SIZE_GUIDE_CATEGORIES = ("mens-sneakers", "womens-kurtas", "mens-shirts")


class Abort(Exception):
    """Raised inside a journey to end it; the outcome has already been filled in."""


@dataclass
class Ctx:
    c: Client
    cat: Catalog
    cfg: dict[str, Any]
    toggles_fn: Callable[[float], dict[str, bool]]
    out: Outcome
    t: float = 0.0
    stage: str = "S1"
    seen_prices: dict[str, float] = field(default_factory=dict)

    @property
    def rng(self) -> random.Random:
        return self.c.rng

    @property
    def spec(self) -> dict[str, Any]:
        return self.c.spec

    def tg(self) -> dict[str, bool]:
        return self.toggles_fn(self.t)

    def p(self, key: str, default: float = 0.0) -> float:
        return float(self.spec.get(key, default))


def think(ctx: Ctx, scale: float = 1.0) -> float:
    model = ctx.spec["think"]
    rng = ctx.rng
    if model["kind"] == "regular":
        value = float(model["interval"]) * (1 + rng.gauss(0, float(model["jitter"])))
    else:
        value = rng.lognormvariate(math.log(float(model["median"])), float(model["sigma"]))
    return max(0.15, value * scale)


def fail(ctx: Ctx, blocker: str | None, stage: str | None = None) -> NoReturn:
    ctx.out.blocker = blocker
    ctx.out.stage_of_failure = stage or ctx.stage
    raise Abort


def stop(ctx: Ctx, stage: str | None = None) -> NoReturn:
    """Voluntary end of the journey without a blocker (task done, or the visitor just left)."""
    ctx.out.stage_of_failure = stage
    raise Abort


def _maybe_leave(ctx: Ctx) -> None:
    noise = ctx.cfg["noise"]["p_random_abandon"]
    if ctx.rng.random() < noise / 6:
        ctx.out.blocker = None
        ctx.out.stage_of_failure = ctx.stage
        raise Abort


def call(ctx: Ctx, req: Req, *, tolerate: bool = False) -> Generator[Req, Resp, Resp]:
    """Send a request and apply the reactions every client shares: retry 5xx, wait out 429, give up on the bot wall."""
    max_retries = int(ctx.cfg["reaction"]["max_retries"])
    retries = 0
    waited = False
    while True:
        resp = yield req
        code = resp.error_code
        if resp.status >= 500 or code == "UPSTREAM_ERROR":
            if retries < max_retries and ctx.rng.random() < 0.85:
                retries += 1
                req = replace(req, think=0.6 + ctx.rng.random() * 2.0)
                continue
            if tolerate:
                return resp
            fail(ctx, None)
        if code == "RATE_LIMITED":
            patient = ctx.p("p_wait_rate_limit", 0.6 if ctx.spec["behavior"] != "human" else 0.3)
            if not waited and ctx.rng.random() < patient:
                waited = True
                wait = float(resp.data.get("retry_after", 60))
                req = replace(req, think=wait + ctx.rng.random() * 3)
                continue
            fail(ctx, "B12")
        if code == "BOT_CHALLENGE":
            if not waited and ctx.rng.random() < 0.25:
                waited = True
                req = replace(req, think=2 + ctx.rng.random() * 4)
                continue
            fail(ctx, "B01")
        return resp


def page(ctx: Ctx, path: str, query: str = "", *, stage: str | None = None, fast: bool = False) -> Generator[Req, Resp, Resp]:
    if stage:
        ctx.stage = stage
    c = ctx.c
    req = Req("GET", path, query, PAGE, think=0.0 if c.pages_seen == 0 and not c.last_page else think(ctx, 0.35 if fast else 1.0),
              referer=c.last_page)  # fmt: skip
    resp = yield from call(ctx, req)
    if resp.status == 404:
        fail(ctx, "B16")
    if resp.status >= 400:
        fail(ctx, None)
    c.last_page = path
    slow = float(ctx.cfg["reaction"]["slow_ms"])
    if resp.duration_ms > slow:
        p_slow = ctx.p("p_abandon_slow", float(ctx.cfg["reaction"]["p_abandon_slow"]) if ctx.spec["behavior"] != "human" else 0.15)
        if ctx.rng.random() < p_slow:
            fail(ctx, "B13")
    _maybe_leave(ctx)
    return resp


def api(ctx: Ctx, method: str, path: str, query: str = "", body: dict[str, Any] | None = None, *, stage: str | None = None,
        fast: bool = False) -> Generator[Req, Resp, Resp]:  # fmt: skip
    if stage:
        ctx.stage = stage
    req = Req(method, path, query, API, body=body, think=think(ctx, 0.25 if fast else 0.45), referer=ctx.c.last_page)
    return (yield from call(ctx, req, tolerate=True))


# ---- targets -----------------------------------------------------------------------------------------------------

def _variant_for(ctx: Ctx, product: dict[str, Any], size: str | None = None) -> dict[str, Any]:
    variants = product["variants"]
    if size:
        match = [v for v in variants if v["size"] == size]
        if match:
            return ctx.rng.choice(match)
    return ctx.rng.choice(variants)


def choose_target(ctx: Ctx, task: str) -> tuple[dict[str, Any], dict[str, Any]]:
    cat, rng = ctx.cat, ctx.rng
    if task == "T1":
        pool = [p for p in cat.in_category("mens-sneakers") if p["price"] < 4000] or cat.in_category("mens-sneakers")
        product = rng.choice(pool)
        whites = [v for v in product["variants"] if v["size"] == "UK 9" and v["colour"] == "White"]
        return product, (whites[0] if whites else _variant_for(ctx, product, "UK 9"))
    if task == "T4":
        product = cat.cheapest("womens-kurtas")
        return product, _variant_for(ctx, product, "M")
    product = cat.pick(rng)
    return product, _variant_for(ctx, product)


def pick_task(ctx: Ctx, default: str) -> str:
    tasks = ctx.spec.get("tasks")
    if not tasks:
        return default
    names = list(tasks)
    return ctx.rng.choices(names, weights=[float(tasks[n]) for n in names])[0]


# ---- shopper flow (browsing agents and humans who intend to buy) -------------------------------------------------

def _pdp_friction(ctx: Ctx) -> None:
    tg = ctx.tg()
    if tg["F07"] and ctx.rng.random() < ctx.p("p_interstitial_abandon"):
        fail(ctx, "B07", "S2")
    if tg["F08"] and ctx.rng.random() < ctx.p("p_spin_abandon"):
        fail(ctx, "B07", "S2")


def _size_guide(ctx: Ctx, product: dict[str, Any]) -> Generator[Req, Resp, None]:
    category = product["category"] if product["category"] in SIZE_GUIDE_CATEGORIES else "mens-shirts"
    yield from page(ctx, f"/size-guide/{category}", stage="S3")
    if ctx.tg()["F09"] and ctx.rng.random() < ctx.p("p_image_guide_fail"):
        fail(ctx, "B09", "S3")


def _check_pincode(ctx: Ctx, stage: str = "S4") -> Generator[Req, Resp, bool]:
    pin = ctx.rng.choice(PINCODES)
    resp = yield from api(ctx, "GET", "/api/serviceability", f"pincode={pin}", stage=stage)
    if resp.status == 422:
        resp = yield from api(ctx, "GET", "/api/serviceability", f"pincode={ctx.rng.choice(PINCODES[:4])}", stage=stage)
    return resp.status == 200


def _login(ctx: Ctx) -> Generator[Req, Resp, bool]:
    yield from page(ctx, "/login", stage="S5", fast=True)
    yield from api(ctx, "POST", "/api/otp/send", body={"phone": ctx.rng.choice(STRICT_PHONES)}, stage="S5")
    if ctx.rng.random() >= ctx.p("p_otp"):
        return False
    otp = "123456" if ctx.rng.random() > 0.1 else "654321"
    resp = yield from api(ctx, "POST", "/api/otp/verify", body={"otp": otp, "purpose": "login"}, stage="S5", fast=True)
    if resp.status == 400 and ctx.rng.random() < 0.9:
        resp = yield from api(ctx, "POST", "/api/otp/verify", body={"otp": "123456", "purpose": "login"}, stage="S5")
    return resp.status == 200


def _add_to_cart(ctx: Ctx, product: dict[str, Any], variant: dict[str, Any]) -> Generator[Req, Resp, Resp]:
    body = {"product_id": product["id"], "size": variant["size"], "colour": variant["colour"], "qty": 1}
    human = ctx.spec["behavior"] == "human"
    alt_path = ctx.p("p_pincode") if human else float(ctx.cfg["reaction"]["p_alt_path"])
    max_same = 0 if human else int(ctx.cfg["reaction"]["max_retries"])
    same = 0
    pincode_done = login_done = False
    for _ in range(8):
        resp = yield from api(ctx, "POST", "/api/cart", body=body, stage="S5")
        if resp.status == 201:
            return resp
        code = resp.error_code
        if code == "PINCODE_REQUIRED":
            if pincode_done:
                fail(ctx, "B05")
            if ctx.rng.random() < alt_path:
                pincode_done = True
                if not (yield from _check_pincode(ctx)):
                    fail(ctx, "B05")
            elif same < max_same:
                same += 1
            else:
                fail(ctx, "B05")
        elif code == "AUTH_REQUIRED":
            if login_done:
                fail(ctx, "B06")
            login_done = True
            if not (yield from _login(ctx)):
                fail(ctx, "B06")
        elif code == "OUT_OF_STOCK":
            fail(ctx, "B08", "S3")
        else:
            fail(ctx, CODE_BLOCKER.get(code or ""))
    fail(ctx, None)


def _variant_step(ctx: Ctx, product: dict[str, Any], variant: dict[str, Any]) -> Generator[Req, Resp, dict[str, Any]]:
    query = f"size={quote_plus(variant['size'])}&colour={quote_plus(variant['colour'])}"
    resp = yield from api(ctx, "GET", f"/api/products/{product['id']}/variants", query, stage="S3")
    if resp.error_code == "OUT_OF_STOCK" or (resp.status == 200 and resp.data.get("in_stock") is False):
        alt_p = float(ctx.cfg["reaction"]["p_alt_path"]) if ctx.spec["behavior"] != "human" else 0.55
        in_stock = [v for v in product["variants"] if v["stock"] > 0]
        if ctx.rng.random() < alt_p and in_stock:
            variant = ctx.rng.choice(in_stock)
            query = f"size={quote_plus(variant['size'])}&colour={quote_plus(variant['colour'])}"
            yield from api(ctx, "GET", f"/api/products/{product['id']}/variants", query, stage="S3")
            return variant
        fail(ctx, "B08", "S3")
    return variant


def _checkout(ctx: Ctx, expect_value: float) -> Generator[Req, Resp, None]:
    rng, c = ctx.rng, ctx.c
    human = ctx.spec["behavior"] == "human"
    yield from page(ctx, "/checkout", stage="S6")
    comp = ctx.cfg["completion"]
    if rng.random() >= float(comp["human_checkout"] if human else comp["browsing_agent_checkout"]):
        stop(ctx, "S6")
    ctx.stage = "S7"
    captcha_answer = ""
    if ctx.tg()["F02"] and c.js:
        resp = yield from api(ctx, "GET", "/api/captcha", fast=True)
        if rng.random() < ctx.p("p_captcha"):
            captcha_answer = str(resp.data.get("answer", ""))
    method = rng.choice(["COD", "COD", "UPI", "CARD"]) if rng.random() < 0.55 else rng.choice(["UPI", "CARD"])
    phone = rng.choice(STRICT_PHONES) if rng.random() < ctx.p("p_phone_strict") else rng.choice(LOOSE_PHONES)
    attempts = 0
    cod_switched = otp_done = False
    for _ in range(8):
        body = {"name": "Asha Verma", "address": "12 MG Road, Gurugram 122001", "phone": phone,
                "payment_method": method, "captcha_answer": captcha_answer}  # fmt: skip
        resp = yield from api(ctx, "POST", "/api/checkout", body=body, stage="S7")
        if resp.status == 201:
            order_id = str(resp.data.get("order_id", ""))
            ctx.out.converted, ctx.out.order_id = True, order_id
            ctx.out.order_value = float(resp.data.get("cart_value", expect_value))
            yield from page(ctx, f"/order/confirmed/{order_id}", stage="S8", fast=True)
            return
        code = resp.error_code
        if code == "PHONE_FORMAT":
            attempts += 1
            if attempts > ctx.cfg["reaction"]["max_retries"] or rng.random() >= ctx.p("p_phone_retry"):
                fail(ctx, "B10")
            phone = rng.choice(STRICT_PHONES) if rng.random() < 0.7 else rng.choice(LOOSE_PHONES)
        elif code == "CAPTCHA_REQUIRED":
            if captcha_answer or not c.js or rng.random() >= ctx.p("p_captcha"):
                fail(ctx, "B02")
            fresh = yield from api(ctx, "GET", "/api/captcha", fast=True)
            captcha_answer = str(fresh.data.get("answer", ""))
        elif code == "COD_OTP_REQUIRED":
            if not cod_switched and rng.random() < ctx.p("p_cod_switch", 0.5):
                cod_switched, method = True, "CARD"
            elif not otp_done and rng.random() < ctx.p("p_otp"):
                otp_done = True
                yield from api(ctx, "POST", "/api/otp/verify", body={"otp": "123456", "purpose": "cod"})
            else:
                fail(ctx, "B11")
        else:
            fail(ctx, CODE_BLOCKER.get(code or ""))
    fail(ctx, None)


def shopper(ctx: Ctx, task: str) -> Generator[Req, Resp, None]:
    rng = ctx.rng
    product, variant = choose_target(ctx, task)
    deep_link = rng.random() < 0.25
    if not deep_link:
        yield from page(ctx, "/", stage="S1")
        if task == "T1":
            yield from page(ctx, "/search", "q=white+sneakers", stage="S1")
        yield from page(ctx, f"/c/{product['category']}", stage="S1")
    yield from page(ctx, f"/p/{product['slug']}", stage="S2")
    ctx.seen_prices[product["id"]] = float(product["price"])
    _pdp_friction(ctx)
    if task == "T2" or rng.random() < ctx.p("p_size_guide", 0.25):
        yield from _size_guide(ctx, product)
    if rng.random() < 0.3 and ctx.spec["behavior"] == "human":
        yield from _check_pincode(ctx)
    variant = yield from _variant_step(ctx, product, variant)
    resp = yield from _add_to_cart(ctx, product, variant)
    unit = float(resp.data.get("unit_price", product["price"]))
    if abs(unit - product["price"]) > 0.5 and rng.random() < ctx.p("p_mismatch_abandon"):
        fail(ctx, "B15", "S5")
    yield from page(ctx, "/cart", stage="S5", fast=True)
    if task == "T4":
        stop(ctx, None)
    yield from _checkout(ctx, float(resp.data.get("cart_value", unit)))


def browse_human(ctx: Ctx) -> Generator[Req, Resp, None]:
    rng = ctx.rng
    yield from page(ctx, "/", stage="S1")
    if rng.random() < 0.7:
        yield from page(ctx, f"/c/{rng.choice(ctx.cat.categories)}", stage="S1")
    for _ in range(rng.choice([0, 1, 1, 2, 3])):
        product = ctx.cat.pick(rng)
        yield from page(ctx, f"/p/{product['slug']}", stage="S2")
        if rng.random() < 0.12:
            yield from _size_guide(ctx, product)
    if rng.random() < 0.15:
        yield from page(ctx, "/policies/returns", stage="S1")


# ---- fetcher flow (user-triggered fetchers: ChatGPT-User, Claude-User, Perplexity-User style) --------------------

def _fetcher_reads_pdp(ctx: Ctx, product: dict[str, Any]) -> Generator[Req, Resp, None]:
    yield from page(ctx, f"/p/{product['slug']}", stage="S2")
    tg = ctx.tg()
    if tg["F03"] and ctx.rng.random() < 0.7:
        fail(ctx, "B03", "S2")
    if tg["F04"] and ctx.rng.random() < 0.4:
        fail(ctx, "B04", "S2")


def fetcher(ctx: Ctx, task: str) -> Generator[Req, Resp, None]:
    rng, cat = ctx.rng, ctx.cat
    needs_pdp = task in ("T1", "T3", "PDP")
    if rng.random() < ctx.p("respects_robots"):
        resp = yield from page(ctx, "/robots.txt", stage="S1")
        if needs_pdp and resp.data.get("disallow_pdp") and rng.random() < 0.9:
            fail(ctx, "B14", "S2")
    if task == "T1":
        yield from page(ctx, "/search", "q=white+sneakers", stage="S1")
        yield from page(ctx, "/c/mens-sneakers", stage="S1", fast=True)
        for _ in range(rng.choice([1, 2, 2, 3])):
            yield from _fetcher_reads_pdp(ctx, rng.choice(cat.in_category("mens-sneakers")))
    elif task == "T2":
        yield from page(ctx, "/size-guide/mens-sneakers", stage="S3")
        if ctx.tg()["F09"] and rng.random() < 0.8:
            fail(ctx, "B09", "S3")
    elif task == "T3":
        yield from _fetcher_reads_pdp(ctx, cat.pick(rng))
        yield from _check_pincode(ctx)
    elif task == "T6":
        yield from page(ctx, "/policies/returns", stage="S1")
    else:
        for _ in range(rng.choice([1, 1, 2, 3])):
            yield from _fetcher_reads_pdp(ctx, cat.pick(rng))


def crawler(ctx: Ctx) -> Generator[Req, Resp, None]:
    rng, cat = ctx.rng, ctx.cat
    lo, hi = ctx.spec["pages"]
    blocked_pdp = False
    resp = yield from page(ctx, "/robots.txt", stage="S1")
    blocked_pdp = bool(resp.data.get("disallow_pdp"))
    for _ in range(rng.randrange(int(lo), int(hi) + 1)):
        roll = rng.random()
        if roll < 0.1:
            yield from page(ctx, "/", stage="S1")
        elif roll < 0.3:
            yield from page(ctx, f"/c/{rng.choice(cat.categories)}", stage="S1")
        elif roll < 0.4:
            yield from page(ctx, "/policies/returns", stage="S1")
        elif not blocked_pdp:
            yield from page(ctx, f"/p/{cat.pick(rng)['slug']}", stage="S2")


# ---- entry point -------------------------------------------------------------------------------------------------

def run_journey(ctx: Ctx) -> Journey:
    behavior = ctx.spec["behavior"]
    try:
        if behavior == "human":
            if ctx.rng.random() < ctx.p("p_intent"):
                ctx.out.task = "T5"
                yield from shopper(ctx, "T5")
            else:
                ctx.out.task = "browse"
                yield from browse_human(ctx)
        elif behavior == "shopper":
            ctx.out.task = pick_task(ctx, "T5")
            yield from shopper(ctx, ctx.out.task)
        elif behavior == "fetcher":
            ctx.out.task = pick_task(ctx, "T1")
            yield from fetcher(ctx, ctx.out.task)
        else:
            ctx.out.task = "crawl"
            yield from crawler(ctx)
    except Abort:
        pass
    return ctx.out
