"""The replay journey: a priority-ordered state machine of shopping actions, each emitting steps and blocker signals.

Fetch mode (this module) uses HTTP + stdlib HTML parsing only. `browser_agent.BrowserJourney` overrides the state-touching
actions with real page interactions. A planner (deterministic or OpenAI) picks among the actions `allowed()` returns.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from agentlens.diagnosis.llm import redact
from agentlens.diagnosis.sitechecks import parse_robots

from .client import BudgetExceeded, HttpResult, ReplayClient
from .config import ReplayConfig, RobotsDisallowed, is_local_host
from .hypotheses import HYPOTHESES
from .model import CONFIRMED, INCONCLUSIVE, NOT_REPRODUCED, Signal, StepRecord
from .observe import (
    ProductPage,
    card_prices,
    parse_product_page,
    product_links,
    size_guide_has_image,
    size_guide_has_table,
    visible_text,
)  # fmt: skip
from .planner import DeterministicPlanner, Planner
from .task import TaskSpec

CONTROL_UA = "AgentLens-ControlProbe/1.0 (non-browser client, no JavaScript)"
STRICT_PHONE_FMT = "+91 {0} {1}"
MAX_CANDIDATES = 6
SKIP_LINK = re.compile(r"^/(_next|img|api|admin|icon|\.well-known)")


@dataclass
class Candidate:
    path: str
    price: int | None


class Journey:
    mode = "fetch"

    def __init__(
        self, cfg: ReplayConfig, client: ReplayClient, task: TaskSpec, *, target: str | None = None,
        planner: Planner | None = None, evidence_dir: Path | None = None, product_hints: tuple[str, ...] = (),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:  # fmt: skip
        self.cfg, self.client, self.task, self.target = cfg, client, task, target
        self.planner = planner or DeterministicPlanner()
        self.evidence_dir = evidence_dir
        self.hints = product_hints
        self.clock = clock
        self.steps: list[StepRecord] = []
        self.signals: list[Signal] = []
        self.workarounds: list[str] = []
        self.notes: list[str] = []
        self.pending: list[str] = []
        self.f: dict[str, bool] = {}
        self.halted = False            # the purchase path cannot continue; only probes remain
        self.stopped = False           # nothing more should run
        self.halt_reason: str | None = None
        self.candidates: list[Candidate] = []
        self.cursor = 0
        self.page: ProductPage | None = None
        self.pdp_html = ""
        self.home_html = ""
        self.search_html = ""
        self.variant: dict[str, Any] | None = None
        self.expected_price: int | None = None
        self.cart_ok = False
        self.ordered = False
        self.confirmed = False
        self.order_id: str | None = None
        self.phone_formatted = False
        self.payment = "COD"
        self.checkout_attempts = 0
        self.chosen_by = "deterministic"
        self.bypass = cfg.bypass_test_walls and is_local_host(client.base_url)

    def close(self) -> None:
        """Release resources held by a subclass (the browser)."""

    # ------------------------------------------------------------------ recording
    def wants(self, bid: str) -> bool:
        return self.target is None or self.target == bid

    def step(
        self, action: str, res: HttpResult | None, note: str, *, method: str | None = None, url: str | None = None,
        evidence: dict[str, Any] | None = None, snapshot: bool = False, screenshot: str | None = None,
    ) -> StepRecord:  # fmt: skip
        n = len(self.steps) + 1
        ev: dict[str, Any] = dict(evidence or {})
        if self.chosen_by != "deterministic":
            ev["chosen_by"] = self.chosen_by
        if res is not None:
            if snapshot and res.text and self.evidence_dir is not None:
                name = f"dom_{n}.txt"
                (self.evidence_dir / name).write_text(visible_text(res.text), encoding="utf-8")
                ev["snapshot"] = name
            elif res.headers.get("content-type", "").startswith("application/json"):
                ev["body"] = redact(res.text[:300])
        rec = StepRecord(
            n=n, action=action, method=res.method if res else method, url=res.url if res else (url or ""),
            status=res.status if res else None, duration_ms=res.duration_ms if res else 0, note=note,
            screenshot=screenshot, evidence=ev,
        )  # fmt: skip
        self.steps.append(rec)
        return rec

    def signal(self, bid: str, present: bool, detail: str, step: StepRecord | None = None, **evidence: Any) -> None:
        step = step or self.steps[-1]
        if any(s.blocker_id == bid and s.present == present for s in self.signals):
            return
        self.signals.append(Signal(bid, present, detail, step.n, evidence))
        step.evidence.setdefault("signals", []).append({"blocker_id": bid, "present": present, "detail": detail})
        if step.blocker_id is None and (present or bid == self.target):
            step.blocker_id = bid

    def halt(self, reason: str) -> None:
        self.halted = True
        self.halt_reason = self.halt_reason or reason
        self.pending = []
        self.notes.append(reason)

    def stop(self, reason: str) -> None:
        self.stopped = True
        self.halt_reason = self.halt_reason or reason
        self.notes.append(reason)

    def present(self, bid: str) -> bool:
        return any(s.blocker_id == bid and s.present for s in self.signals)

    # ------------------------------------------------------------------ HTTP with generic wall handling
    def call(
        self, action: str, method: str, path: str, *, json_body: Any = None, params: dict[str, Any] | None = None,
        note: str = "", snapshot: bool = False, handle_walls: bool = True,
    ) -> tuple[HttpResult | None, StepRecord]:  # fmt: skip
        try:
            res = self.client.request(method, path, json_body=json_body, params=params)
        except RobotsDisallowed as exc:
            rec = self.step(action, None, f"blocked by robots.txt: {exc}", method=method, url=self.client.url(path))
            self.signal("B14", True, str(exc), rec)
            self.stop("robots.txt disallows this path for AgentLens-Replay; the replay honours it")
            return None, rec
        except httpx.TimeoutException as exc:
            rec = self.step(action, None, f"timed out: {type(exc).__name__}", method=method, url=self.client.url(path))
            self.signal("B13", True, f"request timed out after {self.cfg.request_timeout_s:.0f}s", rec)
            self.halt("request timed out")
            return None, rec
        except httpx.HTTPError as exc:
            rec = self.step(action, None, f"network error: {type(exc).__name__}", method=method, url=self.client.url(path))
            self.stop(f"network error {type(exc).__name__}")
            return None, rec
        rec = self.step(action, res, note or f"{method} {urlsplit(res.url).path} -> {res.status}", snapshot=snapshot)
        if handle_walls:
            if res.error_code == "BOT_CHALLENGE":
                self.signal("B01", True, "403 bot challenge served to the AgentLens-Replay user agent", rec)
                self.stop("bot wall blocked the replay agent")
            elif res.status == 429:
                self.signal("B12", True, "429 Too Many Requests", rec)
                self.stop("rate limited; the replay backs off instead of retrying")
        return res, rec

    # ------------------------------------------------------------------ planning
    def allowed(self) -> list[str]:
        if self.stopped:
            return []
        if not self.f.get("robots"):
            return ["robots"]
        if self.halted:
            return self.epilogue()
        if self.pending:
            return list(self.pending)
        if self.wants("B01") and not self.f.get("bot"):
            return ["probe_bot"]
        if not self.f.get("home"):
            return ["open_home"]
        if not self.f.get("search"):
            return ["search"]
        if self.target == "B08" and not self.f.get("oos"):
            return ["probe_oos"]
        if not self.cart_ok:
            if self.page is None:
                return ["open_product"] if self.cursor < len(self.candidates) else self.epilogue(exhausted=True)
            out = []
            if not self.f.get("size_guide"):
                out.append("read_size_guide")
            out.append("add_to_cart" if self.variant else "check_variant")
            return out
        if not self.f.get("cart_verified"):
            return ["verify_cart"]
        if not self.f.get("checkout_open"):
            return ["open_checkout"]
        if not self.ordered:
            return ["submit_checkout"]
        if not self.confirmed:
            return ["confirm_order"]
        return self.epilogue()

    def rate_probe_enabled(self) -> bool:
        return self.target == "B12" and (is_local_host(self.client.base_url) or self.cfg.load_probes)

    def epilogue(self, exhausted: bool = False) -> list[str]:
        out: list[str] = []
        if exhausted and not self.halted:
            self.halt("no candidate product could be bought within the task constraints")
        if self.wants("B16") and not self.f.get("links"):
            out.append("check_links")
        if self.target == "B12" and not self.f.get("rate") and self.rate_probe_enabled():
            out.append("probe_rate")
        return out

    def state_summary(self) -> dict[str, Any]:
        return {
            "stage": "cart" if self.cart_ok else "browse", "steps": len(self.steps),
            "last": [{"action": s.action, "status": s.status} for s in self.steps[-3:]],
            "candidates_left": max(0, len(self.candidates) - self.cursor), "pending": self.pending,
            "target": self.target,
        }  # fmt: skip

    def run(self) -> None:
        deadline = self.clock() + self.cfg.max_seconds
        self.client.deadline = deadline
        while not self.stopped:
            if len(self.steps) >= self.cfg.max_steps:
                self.notes.append(f"step budget of {self.cfg.max_steps} reached")
                break
            if self.clock() > deadline:
                self.notes.append(f"time budget of {self.cfg.max_seconds:.0f}s reached")
                break
            allowed = self.allowed()
            if not allowed:
                break
            decision = self.planner.decide(self.task.text, self.state_summary(), allowed)
            self.chosen_by = decision.source
            try:
                getattr(self, f"act_{decision.action}")()
            except BudgetExceeded as exc:
                self.notes.append(f"budget: {exc}")
                break
            if self.target and self.present(self.target):
                self.stop(f"{self.target} reproduced; stopping early")

    # ------------------------------------------------------------------ actions: discovery
    def act_robots(self) -> None:
        try:
            self.client.ensure_robots()
        except httpx.HTTPError as exc:
            self.f["robots"] = True
            self.step("robots", None, f"could not read robots.txt: {type(exc).__name__}", url=self.client.url("/robots.txt"))
            self.stop("store unreachable")
            return
        self.f["robots"] = True
        res = self.client.robots_result
        assert res is not None
        rec = self.step("robots", res, "read robots.txt", snapshot=True)
        tokens = parse_robots(res.text, "/p/") if res.status == 200 else []
        if tokens:
            self.signal("B14", True, f"robots.txt disallows /p/ for agent tokens: {', '.join(tokens[:6])}", rec, tokens=tokens)
        else:
            self.signal("B14", False, "robots.txt does not disallow product pages for known agent tokens", rec)

    def act_probe_bot(self) -> None:
        self.f["bot"] = True
        try:
            res = self.client.request("GET", "/", user_agent=CONTROL_UA, check_robots=False)
        except httpx.HTTPError:
            self.step("probe_bot", None, "control probe failed", url=self.client.url("/"))
            return
        rec = self.step("probe_bot", res, f"control probe with a generic non-browser user agent -> {res.status}")
        if res.error_code == "BOT_CHALLENGE" or (res.status in (403, 503) and "challenge" in res.text[:3000].lower()):
            self.signal("B01", True, "generic non-browser clients receive a 403 bot challenge", rec)
            self.workarounds.append("AgentLens-Replay UA is exempt from the demo store's bot wall; control probe used")
        else:
            self.signal("B01", False, f"generic non-browser client was served normally ({res.status})", rec)

    def act_open_home(self) -> None:
        self.f["home"] = True
        res, _ = self.call("open_home", "GET", "/", note="open home page")
        self.home_html = res.text if res else ""

    def act_search(self) -> None:
        self.f["search"] = True
        res, rec = self.call("search", "GET", f"/search?q={quote(self.task.query)}", note=f"search '{self.task.query}'")
        if res is None:
            return
        self.search_html = res.text
        prices = card_prices(res.text)
        links = [h for h in product_links(res.text)]
        cands = [Candidate(h, prices.get(h)) for h in links]
        if self.task.max_price:
            within = [c for c in cands if c.price is None or c.price <= self.task.max_price]
            if len(within) < len(cands):
                rec.note += f"; {len(cands) - len(within)} over budget dropped"
            cands = within
        hinted = [Candidate(f"/p/{h}", None) for h in self.hints if f"/p/{h}" not in [c.path for c in cands]]
        self.candidates = (hinted + cands)[:MAX_CANDIDATES]
        rec.note += f"; {len(self.candidates)} candidate products"
        if not self.candidates:
            self.halt("search returned no product within the task constraints")

    # ------------------------------------------------------------------ actions: product page
    def act_open_product(self) -> None:
        self.fetch_product(modal=True)

    def fetch_product(self, *, modal: bool) -> bool:
        """GET the next candidate's HTML and emit the server-side signals (B03, B04, B13, B16, and B05 if `modal`)."""
        cand = self.candidates[self.cursor]
        self.cursor += 1
        slug = cand.path.rsplit("/", 1)[-1]
        res, rec = self.call("open_product", "GET", cand.path, note=f"open product page {cand.path}", snapshot=True)
        self.page, self.variant, self.pdp_html = None, None, ""
        if res is None:
            return False
        if res.status == 404:
            self.signal("B16", True, f"{cand.path} (linked from search results) returned 404", rec)
            return False
        if not res.ok:
            rec.note += " (skipped)"
            return False
        page = parse_product_page(slug, res.text)
        self.page, self.pdp_html = page, res.text
        if page.server_price is None:
            self.signal("B03", True, "no price in server-rendered HTML or JSON-LD (client-side only)", rec)
        else:
            self.signal("B03", False, f"price ₹{page.server_price} is in the server HTML ({page.price_source})", rec)
        self.signal("B04", not page.has_json_ld,
                    "no JSON-LD Product block" if not page.has_json_ld else "JSON-LD Product block present", rec)  # fmt: skip
        slow = res.duration_ms > self.cfg.slow_pdp_ms
        self.signal("B13", slow, f"product page took {res.duration_ms} ms (limit {self.cfg.slow_pdp_ms} ms)", rec,
                    duration_ms=res.duration_ms)  # fmt: skip
        if modal and page.pincode_modal:
            self.signal("B05", True, "a pincode modal is server-rendered on the product page and blocks interaction", rec)
            if not self.f.get("pincode_entered"):
                self.pending = ["check_delivery"]
        return True

    def act_read_size_guide(self) -> None:
        self.f["size_guide"] = True
        m = re.search(r'href="(/size-guide/[a-z0-9-]+)"', self.pdp_html) or re.search(
            r'href="(/size-guide/[a-z0-9-]+)"', self.home_html
        )
        path = m.group(1) if m else "/size-guide/mens-shirts"
        res, rec = self.call("read_size_guide", "GET", path, note=f"read size guide {path}")
        if res is None or not res.ok:
            return
        table, image = size_guide_has_table(res.text), size_guide_has_image(res.text)
        if image and not table:
            self.signal("B09", True, "size guide is an image only; no HTML table to read", rec, image=True, table=False)
        elif table:
            self.signal("B09", False, "size guide has a machine-readable HTML table", rec, table=True)

    def _pick_colour(self) -> str | None:
        assert self.page is not None
        if not self.page.colours:
            return None
        want = (self.task.colour or "").lower()
        for c in self.page.colours:
            if want and want in c.lower():
                return c
        return None if want else self.page.colours[0]

    def act_check_variant(self) -> None:
        page = self.page
        assert page is not None
        colour = self._pick_colour()
        size = self.task.size or (page.sizes[0] if page.sizes else None)
        if page.colours and colour is None:
            self.step("check_variant", None, f"{page.slug}: no {self.task.colour} colour; trying next product", url=page.slug)
            self.page = None
            return
        params = {k: v for k, v in (("size", size), ("colour", colour)) if v}
        res, rec = self.call("check_variant", "GET", f"/api/products/{page.slug}/variants", params=params,
                             note=f"check {size}/{colour} availability")  # fmt: skip
        if res is None:
            return
        data = res.json() if isinstance(res.json(), dict) else {}
        if res.status == 409 and res.error_code == "OUT_OF_STOCK":
            self.signal("B08", True, f"{page.slug} {size}/{colour} is out of stock and no alternative is offered (409)", rec)
            self.page = None
        elif res.ok and data.get("available") is False:
            self.signal("B08", False, "out-of-stock variant came with in-stock alternatives", rec)
            self.workarounds.append(f"{page.slug} {size}/{colour} out of stock; alternatives were offered, tried next product")
            self.page = None
        elif res.ok and data.get("available"):
            price = int(data.get("price") or 0) or page.server_price
            if self.task.max_price and price and price > self.task.max_price:
                rec.note += f"; ₹{price} is over budget, trying next product"
                self.page = None
                return
            self.variant = {"size": size, "colour": colour, "price": price}
            self.expected_price = price
        else:
            rec.note += "; variant not found, trying next product"
            self.page = None

    def act_probe_oos(self) -> None:
        self.f["oos"] = True
        want_colour = (self.task.colour or "").lower()
        for cand in self.candidates[:MAX_CANDIDATES]:
            slug = cand.path.rsplit("/", 1)[-1]
            res, rec = self.call("probe_oos", "GET", f"/api/products/{slug}/variants", note=f"list variants of {slug}")
            if res is None or not res.ok:
                continue
            for v in res.json().get("variants", []):
                if v.get("available") is False and (not self.task.size or v.get("size", "").upper() == self.task.size) and (
                    not want_colour or want_colour in v.get("colour", "").lower()
                ):
                    r2, rec2 = self.call("probe_oos", "GET", f"/api/products/{slug}/variants",
                                         params={"size": v["size"], "colour": v["colour"]},
                                         note=f"select out-of-stock variant {v['size']}/{v['colour']}")  # fmt: skip
                    if r2 is None:
                        return
                    if r2.status == 409:
                        self.signal("B08", True, f"{slug} {v['size']}/{v['colour']}: 409 with no alternative offered", rec2)
                    elif r2.ok and r2.json().get("alternatives"):
                        self.signal("B08", False, "out-of-stock variant came with in-stock alternatives", rec2)
                    return

    # ------------------------------------------------------------------ actions: cart
    def act_add_to_cart(self) -> None:
        page, variant = self.page, self.variant
        assert page is not None and variant is not None
        body = {"slug": page.slug, "size": variant["size"], "colour": variant["colour"], "qty": 1}
        res, rec = self.call("add_to_cart", "POST", "/api/cart", json_body=body, note=f"add {page.slug} to cart")
        if res is None:
            return
        self.cart_outcome(rec, res.status, res.error_code, res.json())

    def cart_outcome(self, rec: StepRecord, status: int, code: str | None, data: Any) -> None:
        if status == 201:
            self.cart_ok = True
            rec.evidence["unit_price"] = data.get("unit_price") if isinstance(data, dict) else None
            if not self.f.get("pincode_entered"):
                self.signal("B05", False, "add to cart succeeded without a pincode check", rec)
            if not self.f.get("otp_done"):
                self.signal("B06", False, "add to cart succeeded without an OTP login", rec)
        elif code == "PINCODE_REQUIRED":
            self.signal("B05", True, "add to cart rejected with 409 PINCODE_REQUIRED until a pincode is validated", rec)
            if self.f.get("pincode_entered"):
                self.halt("pincode wall persisted after entering a valid pincode")
            else:
                self.pending = ["check_delivery"]
        elif code == "AUTH_REQUIRED":
            self.signal("B06", True, "add to cart rejected with 401 AUTH_REQUIRED (OTP login before cart)", rec)
            if self.bypass and not self.f.get("otp_done"):
                self.pending = ["otp_send"]
            else:
                self.halt("login/OTP wall: the OTP is sent by SMS and an agent cannot read it, so the replay stops here")
        elif code == "OUT_OF_STOCK":
            self.signal("B08", True, "add to cart returned 409 OUT_OF_STOCK", rec)
            self.page, self.variant = None, None
        else:
            rec.note += "; add to cart failed, trying next product"
            self.page, self.variant = None, None

    def act_check_delivery(self) -> None:
        pin = self.task.pincode or self.cfg.test_profile["pincode"]
        self.pending = []
        res, rec = self.call("check_delivery", "GET", "/api/serviceability", params={"pincode": pin},
                             note=f"check delivery to test pincode {pin}")  # fmt: skip
        if res is None:
            return
        self.delivery_outcome(res.ok, pin)

    def delivery_outcome(self, ok: bool, pin: str) -> None:
        if ok:
            self.f["pincode_entered"] = True
            self.workarounds.append(f"entered test pincode {pin} to pass the pincode wall")
        else:
            self.halt(f"pincode {pin} is not serviceable")

    def act_otp_send(self) -> None:
        res, _ = self.call("otp_send", "POST", "/api/otp/send", json_body={"phone": self.cfg.test_profile["phone"],
                           "purpose": "login"}, note="request a login OTP for the test phone number")  # fmt: skip
        if res is not None and res.ok:
            self.pending = ["otp_verify"]
        else:
            self.halt("OTP could not be requested")

    def act_otp_verify(self) -> None:
        res, _ = self.call("otp_verify", "POST", "/api/otp/verify", json_body={"otp": self.cfg.test_otp,
                           "purpose": "login"}, note="submit the store's documented test OTP (local test hosts only)")  # fmt: skip
        self.otp_outcome(res is not None and res.ok)

    def otp_outcome(self, ok: bool) -> None:
        self.pending = []
        if ok:
            self.f["otp_done"] = True
            self.workarounds.append("verified with the demo store's fixed test OTP (test hosts only, never real SMS)")
        else:
            self.halt("test OTP was not accepted")

    def act_verify_cart(self) -> None:
        self.f["cart_verified"] = True
        res, rec = self.call("verify_cart", "GET", "/api/cart", note="read the cart and compare prices")
        if res is None or not res.ok:
            return
        items = res.json().get("items", [])
        if not items:
            return
        unit = items[0].get("unit_price")
        if self.expected_price and isinstance(unit, int | float):
            if int(unit) != int(self.expected_price):
                self.signal("B15", True, f"cart price ₹{int(unit)} differs from product page price ₹{self.expected_price}", rec,
                            pdp_price=self.expected_price, cart_price=int(unit))  # fmt: skip
            else:
                self.signal("B15", False, f"cart price matches the product page (₹{int(unit)})", rec)

    # ------------------------------------------------------------------ actions: checkout
    def act_open_checkout(self) -> None:
        self.f["checkout_open"] = True
        self.call("open_checkout", "GET", "/checkout", note="open checkout page")

    def _checkout_body(self) -> dict[str, str]:
        p = self.cfg.test_profile
        phone = p["phone"]
        if self.phone_formatted:
            phone = STRICT_PHONE_FMT.format(phone[-10:-5], phone[-5:])
        return {"name": p["name"], "phone": phone, "address": p["address"], "pincode": self.task.pincode or p["pincode"],
                "payment_method": self.payment, "captcha_answer": "", "cod_otp": ""}  # fmt: skip

    def act_submit_checkout(self) -> None:
        self.checkout_attempts += 1
        if self.checkout_attempts > 4:
            self.halt("checkout still failing after 4 attempts")
            return
        res, rec = self.call("submit_checkout", "POST", "/api/checkout", json_body=self._checkout_body(),
                             note=f"submit checkout ({self.payment}, {'formatted' if self.phone_formatted else 'plain'} phone)")  # fmt: skip
        if res is None:
            return
        self.checkout_outcome(rec, res.status, res.error_code, res.json())

    def checkout_outcome(self, rec: StepRecord, status: int, code: str | None, data: Any) -> None:
        if status == 201:
            self.ordered, self.order_id = True, str(data.get("order_id")) if isinstance(data, dict) else None
            if not self.present("B02"):
                self.signal("B02", False, "checkout accepted without a captcha", rec)
            if not self.present("B10"):
                self.signal("B10", False, "checkout accepted a plain 10-digit phone number", rec)
            if self.payment == "COD" and not self.present("B11"):
                self.signal("B11", False, "COD order placed without an extra OTP step", rec)
            return
        if code == "CAPTCHA_REQUIRED":
            self.signal("B02", True, "checkout requires a captcha before submit; the replay never solves captchas", rec)
            self.halt("captcha at checkout (never solved by the replay agent)")
        elif code == "PHONE_FORMAT":
            self.signal("B02", False, "no captcha was required", rec)
            self.signal("B10", True, "checkout rejected a plain 10-digit phone (422 PHONE_FORMAT); only '+91 XXXXX XXXXX' passes", rec)
            if self.phone_formatted:
                self.halt("phone still rejected after reformatting")
            else:
                self.phone_formatted = True
                self.workarounds.append("re-entered the phone as '+91 XXXXX XXXXX' to satisfy strict validation")
        elif code == "COD_OTP_REQUIRED":
            self.signal("B02", False, "no captcha was required", rec)
            self.signal("B11", True, "cash on delivery needs an OTP confirmation (409 COD_OTP_REQUIRED)", rec)
            if self.payment == "COD":
                self.payment = "UPI"
                self.workarounds.append("switched payment from COD to UPI to avoid the COD OTP step")
            else:
                self.halt("payment step still blocked")
        else:
            self.halt(f"checkout failed: {status} {code or ''}".strip())

    def act_confirm_order(self) -> None:
        self.confirmed = True
        res, _ = self.call("confirm_order", "GET", f"/order/confirmed/{self.order_id}", note="open the order confirmation page")
        if res is not None and not res.ok:
            self.notes.append("order confirmation page did not load")

    # ------------------------------------------------------------------ actions: probes
    def act_check_links(self) -> None:
        self.f["links"] = True
        seen = {s.url for s in self.steps}
        links: list[str] = []
        for html_text in (self.home_html, self.search_html, self.pdp_html):
            for m in re.finditer(r'href="(/[^"#]*)"', html_text):
                p = m.group(1)
                if not SKIP_LINK.match(p) and p not in links and self.client.url(p) not in seen:
                    links.append(p)
        bad: list[str] = []
        checked = 0
        for p in links[:8]:
            res, rec = self.call("check_links", "GET", p, note=f"follow internal link {p}")
            if res is None:
                break
            checked += 1
            if res.status == 404 or res.status >= 500:
                bad.append(p)
                self.signal("B16", True, f"{p} returned {res.status}", rec)
        if checked and not bad:
            self.signal("B16", False, f"{checked} internal links checked, none broken", self.steps[-1])
        elif not checked and not self.stopped:
            self.notes.append("no internal links to check")

    def act_probe_rate(self) -> None:
        self.f["rate"] = True
        n, first_429 = self.cfg.load_probe_requests, None
        old_pause = self.client.pause_s
        self.client.pause_s = self.cfg.load_probe_pause_s
        last: HttpResult | None = None
        try:
            for i in range(1, n + 1):
                last = self.client.request("GET", "/search?q=shirt")
                if last.status == 429:
                    first_429 = i
                    break
        except httpx.HTTPError:
            pass
        finally:
            self.client.pause_s = old_pause
        rec = self.step("probe_rate", last, f"burst of up to {n} search requests (bounded load probe on a test host)",
                        evidence={"requests_sent": first_429 or n, "first_429_at": first_429})  # fmt: skip
        if first_429:
            self.signal("B12", True, f"429 Too Many Requests after {first_429} rapid requests", rec)
        else:
            self.signal("B12", False, f"{n} rapid requests were all served", rec)

    # ------------------------------------------------------------------ outcome
    def outcome(self) -> tuple[str, str]:
        if self.target is None:
            seen = sorted({s.blocker_id for s in self.signals if s.present})
            if seen:
                names = ", ".join(seen)
                return CONFIRMED, f"Observed {names} during an end-to-end run; task {'completed' if self.ordered else 'not completed'}."
            if self.ordered:
                return NOT_REPRODUCED, "Task completed end to end with no blocker observed."
            return INCONCLUSIVE, f"Task not completed and no blocker observed. {self.halt_reason or ''}".strip()
        h = HYPOTHESES.get(self.target)
        title = f"{self.target} ({h.summary})" if h else self.target
        mine = [s for s in self.signals if s.blocker_id == self.target]
        present = [s for s in mine if s.present]
        if present:
            s = present[0]
            return CONFIRMED, f"Reproduced {title}: {s.detail} (step {s.step_n})."
        if mine:
            s = mine[0]
            return NOT_REPRODUCED, (f"Not reproduced {title}: {s.detail} (step {s.step_n}). "
                                    "Covers this task and path only; the store may differ for other products or sessions.")  # fmt: skip
        why = h.inconclusive_hint if h else "the hypothesis has no detector"
        if h and self.mode not in h.modes:
            why = h.inconclusive_hint
        extra = f" Journey halted: {self.halt_reason}." if self.halt_reason else ""
        return INCONCLUSIVE, f"Inconclusive for {title}: {why}.{extra}"
