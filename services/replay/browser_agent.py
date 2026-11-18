"""Browser-mode journey (Playwright Chromium). Opt-in: `--mode browser`; vision needs `--vision` and an OpenAI key.

Stateless server-side checks (robots, size guide, variants API, link check, product HTML analysis) reuse the fetch client; every
state-changing step (pincode, OTP login, add to cart, checkout) is driven through the page, and the page's own network
responses feed the same blocker signals. The browser context only reaches allow-listed hosts, honours robots.txt for
navigations, never solves captchas and identifies itself with the AgentLens-Replay UA.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .client import ReplayClient
from .config import ReplayConfig
from .journey import STRICT_PHONE_FMT, Journey
from .llm import ReplayLLM
from .model import StepRecord
from .planner import Planner
from .task import TaskSpec

NAV_TIMEOUT_MS = 30_000
OVERLAY_WAIT_MS = 8_000
VISION_SYSTEM = (
    "You inspect a screenshot of a shopping website for a test agent. Reply as JSON: "
    '{"overlay_blocking": bool, "captcha_visible": bool, "login_wall": bool, "summary": "<one sentence>"}.'
)


def chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            return Path(p.chromium.executable_path).exists()
    except Exception:  # noqa: BLE001 - any failure means the browser cannot be used
        return False


class BrowserJourney(Journey):
    mode = "browser"

    def __init__(
        self, cfg: ReplayConfig, client: ReplayClient, task: TaskSpec, *, target: str | None = None,
        planner: Planner | None = None, evidence_dir: Path | None = None, product_hints: tuple[str, ...] = (),
        vision_llm: ReplayLLM | None = None,
    ) -> None:  # fmt: skip
        super().__init__(cfg, client, task, target=target, planner=planner, evidence_dir=evidence_dir,
                         product_hints=product_hints)  # fmt: skip
        from playwright.sync_api import sync_playwright

        self.vision = vision_llm
        self._vision_before = vision_llm.tokens_used if vision_llm else 0
        self.browser_network: list[dict[str, Any]] = []
        self.blocked_requests: list[str] = []
        self._bodies: dict[str, bytes] = {}
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._ctx = self._browser.new_context(user_agent=cfg.user_agent, viewport={"width": 1280, "height": 900})
        self._ctx.route("**/*", self._route)
        self.pg = self._ctx.new_page()
        self.pg.set_default_timeout(15_000)
        self.pg.on("response", self._on_response)
        self._last_nav: float | None = None

    @property
    def vision_tokens(self) -> int:
        return (self.vision.tokens_used - self._vision_before) if self.vision else 0

    def close(self) -> None:
        for closer in (self._ctx.close, self._browser.close, self._pw.stop):
            try:
                closer()
            except Exception:  # noqa: BLE001, S110 - shutting down
                pass

    # ------------------------------------------------------------------ plumbing
    def _route(self, route: Any) -> None:
        url = route.request.url
        if url.startswith(("data:", "blob:", "about:")):
            route.continue_()
        elif self.cfg.allow_list.allows(url):
            if route.request.resource_type in ("fetch", "xhr"):
                # keep our own copy of API bodies: Chromium drops them when the page navigates right after the call
                try:
                    resp = route.fetch()
                    self._bodies[urlsplit(url).path] = resp.body()
                    route.fulfill(response=resp)
                    return
                except Exception:  # noqa: BLE001, S110 - fall through to a plain continue
                    pass
            route.continue_()
        else:
            self.blocked_requests.append(url)
            route.abort()

    def _json(self, resp: Any) -> dict[str, Any]:
        if "json" not in (resp.headers.get("content-type") or ""):
            return {}
        raw = self._bodies.get(urlsplit(resp.url).path)
        try:
            data = json.loads(raw) if raw is not None else resp.json()
        except Exception:  # noqa: BLE001
            return {}
        return data if isinstance(data, dict) else {}

    def _on_response(self, resp: Any) -> None:
        req = resp.request
        if req.resource_type not in ("document", "fetch", "xhr"):
            return
        code = None
        if resp.status >= 400 and "json" in (resp.headers.get("content-type") or ""):
            try:
                code = (self._json(resp) or {}).get("error_code")
            except Exception:  # noqa: BLE001
                code = None
        timing = req.timing
        dur = int(timing.get("responseEnd", 0)) if isinstance(timing, dict) and timing.get("responseEnd", 0) > 0 else 0
        self.browser_network.append({
            "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z", "method": req.method, "url": resp.url,
            "status": resp.status, "duration_ms": dur, "error_code": code,
        })  # fmt: skip

    def _pause(self) -> None:
        if self._last_nav is not None and self.client.pause_s > 0:
            wait = self.client.pause_s - (time.monotonic() - self._last_nav)
            if wait > 0:
                time.sleep(wait)
        self._last_nav = time.monotonic()

    def _goto(self, path: str) -> int | None:
        url = self.client.url(path)
        self.cfg.allow_list.check(url)
        self._pause()
        resp = self.pg.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        try:
            self.pg.wait_for_load_state("networkidle", timeout=6_000)
        except Exception:  # noqa: BLE001 - long polling pages are fine
            pass
        self.pg.wait_for_timeout(500)
        return resp.status if resp else None

    def _shot(self, rec: StepRecord, tag: str = "") -> None:
        if self.evidence_dir is None:
            return
        name = f"step_{rec.n}{tag}.png"
        try:
            self.pg.screenshot(path=str(self.evidence_dir / name))
        except Exception:  # noqa: BLE001
            return
        rec.screenshot = name

    def _visible(self, testid: str) -> bool:
        try:
            return self.pg.locator(f'[data-testid="{testid}"]').first.is_visible()
        except Exception:  # noqa: BLE001
            return False

    def _browser_step(self, action: str, note: str, status: int | None = None, **evidence: Any) -> StepRecord:
        rec = self.step(action, None, note, method="BROWSER", url=self.pg.url, evidence=evidence)
        rec.status = status
        return rec

    def _vision_check(self, rec: StepRecord) -> None:
        if self.vision is None or rec.screenshot is None or self.evidence_dir is None or self.vision.calls >= 3:
            return
        out = self.vision.chat_json(VISION_SYSTEM, "Describe blockers visible on this page.",
                                    image=self.evidence_dir / rec.screenshot)  # fmt: skip
        if out:
            rec.evidence["vision"] = {k: out.get(k) for k in ("overlay_blocking", "captcha_visible", "login_wall", "summary")}

    def _robots_ok(self, path: str, rec_action: str) -> bool:
        if not self.cfg.respect_robots or self.client.robots_allows(path):
            return True
        rec = self._browser_step(rec_action, f"robots.txt disallows {path}; not navigating")
        self.signal("B14", True, f"robots.txt disallows {path} for AgentLens-Replay", rec)
        self.stop("robots.txt disallows this path; the replay honours it")
        return False

    def _handle_overlays(self, rec: StepRecord) -> None:
        """Detect (and, as a normal visitor would, dismiss) full-screen overlays; the delay they cause is the evidence."""
        t0 = time.monotonic()
        if self._visible("spin-wheel"):
            self.signal("B07", True, "a spin-the-wheel popup covers the page on arrival", rec, overlay="spin-wheel")
            self._shot(rec, "_overlay")
            try:
                self.pg.get_by_text("No thanks").click(timeout=3_000)
            except Exception:  # noqa: BLE001
                self.pg.keyboard.press("Escape")
        if self._visible("app-interstitial"):
            self._shot(rec, "_overlay")
            closable = False
            try:
                self.pg.locator('[data-testid="app-interstitial-close"]').wait_for(state="visible", timeout=OVERLAY_WAIT_MS)
                self.pg.locator('[data-testid="app-interstitial-close"]').click()
                closable = True
            except Exception:  # noqa: BLE001
                self.pg.keyboard.press("Escape")
            waited = int((time.monotonic() - t0) * 1000)
            self.signal("B07", True, f"a full-screen app-download interstitial covers the product page (close button "
                        f"{'appeared after' if closable else 'did not appear within'} {waited} ms)", rec, overlay="app-interstitial",
                        blocked_ms=waited)  # fmt: skip
        if not self.present("B07") and not self._visible("pincode-modal"):
            self.signal("B07", False, "no full-screen overlay appeared in the rendered page", rec)

    # ------------------------------------------------------------------ actions
    def act_open_home(self) -> None:
        self.f["home"] = True
        if not self._robots_ok("/", "open_home"):
            return
        status = self._goto("/")
        self.home_html = self.pg.content()
        rec = self._browser_step("open_home", "open home page in the browser", status)
        self._shot(rec)
        self._handle_overlays(rec)
        self._vision_check(rec)

    def act_open_product(self) -> None:
        cand = self.candidates[self.cursor]
        if not self._robots_ok(cand.path, "open_product"):
            return
        if not self.fetch_product(modal=False):
            return
        status = self._goto(cand.path)
        rec = self._browser_step("render_product", f"render {cand.path} in the browser", status)
        self._shot(rec)
        self._handle_overlays(rec)
        if self._visible("pincode-modal"):
            self.signal("B05", True, "a pincode modal blocks the rendered product page", rec)
            self._shot(rec, "_modal")
            if not self.f.get("pincode_entered"):
                self.pending = ["check_delivery"]
        self._vision_check(rec)

    def _select_variant(self) -> None:
        assert self.variant is not None
        for tid in (f"colour-{self.variant['colour']}", f"size-{self.variant['size']}"):
            loc = self.pg.locator(f'[data-testid="{tid}"]')
            if loc.count():
                loc.first.click(timeout=5_000)

    def act_add_to_cart(self) -> None:
        page = self.page
        assert page is not None and self.variant is not None
        if "/p/" not in self.pg.url or page.slug not in self.pg.url:
            self._goto(f"/p/{page.slug}")
            self._handle_overlays(self._browser_step("render_product", "re-open product page"))
        self._select_variant()
        try:
            with self.pg.expect_response(lambda r: urlsplit(r.url).path == "/api/cart" and r.request.method == "POST",
                                         timeout=8_000) as info:  # fmt: skip
                self.pg.locator('[data-testid="add-to-cart"]').click(timeout=5_000)
            resp = info.value
            data = self._json(resp)
            status = resp.status
        except Exception as exc:  # noqa: BLE001
            rec = self._browser_step("add_to_cart", f"add to cart did not complete: {type(exc).__name__}")
            self._shot(rec)
            self.page, self.variant = None, None
            return
        rec = self._browser_step("add_to_cart", f"click Add to cart for {page.slug} -> {status}", status)
        self._shot(rec)
        code = data.get("error_code") if isinstance(data, dict) else None
        self.cart_outcome(rec, status, code, data)

    def act_check_delivery(self) -> None:
        pin = self.task.pincode or self.cfg.test_profile["pincode"]
        self.pending = []
        modal = self._visible("pincode-modal")
        field = self.pg.locator('[data-testid="pincode-modal-input"]' if modal else '[data-testid="pincode-input"]').first
        field.fill(pin)
        try:
            with self.pg.expect_response(lambda r: urlsplit(r.url).path == "/api/serviceability", timeout=8_000) as info:
                if modal:
                    self.pg.locator('[data-testid="pincode-modal"] button[type="submit"]').click()
                else:
                    self.pg.get_by_role("button", name="Check", exact=True).click()
            status = info.value.status
        except Exception as exc:  # noqa: BLE001
            rec = self._browser_step("check_delivery", f"pincode check did not complete: {type(exc).__name__}")
            self.halt("pincode check failed in the browser")
            self._shot(rec)
            return
        rec = self._browser_step("check_delivery", f"enter test pincode {pin} -> {status}", status)
        self._shot(rec)
        self.delivery_outcome(status == 200, pin)

    def act_otp_send(self) -> None:
        phone = self.cfg.test_profile["phone"][-10:]
        self._goto(f"/login?next={'/p/' + self.page.slug if self.page else '/'}")
        self.pg.locator('[data-testid="login-phone"]').fill(phone)
        try:
            with self.pg.expect_response(lambda r: urlsplit(r.url).path == "/api/otp/send", timeout=8_000) as info:
                self.pg.get_by_role("button", name="Send OTP").click()
            status = info.value.status
        except Exception:  # noqa: BLE001
            status = 0
        rec = self._browser_step("otp_send", "request a login OTP for the test phone number", status)
        self._shot(rec)
        if status == 200:
            self.pending = ["otp_verify"]
        else:
            self.halt("OTP could not be requested")

    def act_otp_verify(self) -> None:
        self.pg.locator('[data-testid="login-otp"]').fill(self.cfg.test_otp)
        try:
            with self.pg.expect_response(lambda r: urlsplit(r.url).path == "/api/otp/verify", timeout=8_000) as info:
                self.pg.get_by_role("button", name="Verify and continue").click()
            status = info.value.status
            self.pg.wait_for_load_state("domcontentloaded")
        except Exception:  # noqa: BLE001
            status = 0
        rec = self._browser_step("otp_verify", "submit the store's documented test OTP (local test hosts only)", status)
        self._shot(rec)
        self.otp_outcome(status == 200)

    def act_verify_cart(self) -> None:
        self.f["cart_verified"] = True
        status = self._goto("/cart")
        rec = self._browser_step("verify_cart", "open the cart page", status)
        self._shot(rec)
        resp = self._ctx.request.get(self.client.url("/api/cart"))
        items = (self._json(resp) or {}).get("items", []) if resp.ok else []
        if items and self.expected_price:
            unit = int(items[0].get("unit_price", 0))
            if unit != int(self.expected_price):
                self.signal("B15", True, f"cart price ₹{unit} differs from product page price ₹{self.expected_price}", rec,
                            pdp_price=self.expected_price, cart_price=unit)  # fmt: skip
            else:
                self.signal("B15", False, f"cart price matches the product page (₹{unit})", rec)

    def act_open_checkout(self) -> None:
        self.f["checkout_open"] = True
        status = self._goto("/checkout")
        rec = self._browser_step("open_checkout", "open checkout page", status)
        self._shot(rec)
        if self._visible("co-captcha"):
            self.signal("B02", True, "a captcha field is shown at checkout; the replay never solves captchas", rec)
            self.halt("captcha at checkout (never solved by the replay agent)")
        self._vision_check(rec)

    def act_submit_checkout(self) -> None:
        self.checkout_attempts += 1
        if self.checkout_attempts > 4:
            self.halt("checkout still failing after 4 attempts")
            return
        p = self.cfg.test_profile
        if "/checkout" not in self.pg.url:
            self._goto("/checkout")
        phone = p["phone"] if not self.phone_formatted else STRICT_PHONE_FMT.format(p["phone"][-10:-5], p["phone"][-5:])
        for tid, val in (("co-name", p["name"]), ("co-phone", phone), ("co-address", p["address"]),
                         ("co-pincode", self.task.pincode or p["pincode"])):  # fmt: skip
            loc = self.pg.locator(f'[data-testid="{tid}"]')
            if loc.count():
                loc.first.fill(val)
        if self._visible("co-captcha"):
            rec = self._browser_step("submit_checkout", "captcha present; not attempting to solve it")
            self._shot(rec)
            self.signal("B02", True, "a captcha field is shown at checkout; the replay never solves captchas", rec)
            self.halt("captcha at checkout (never solved by the replay agent)")
            return
        pay = self.pg.locator(f'[data-testid="pay-{self.payment}"]')
        if pay.count():
            pay.first.check()
        try:
            with self.pg.expect_response(lambda r: urlsplit(r.url).path == "/api/checkout", timeout=10_000) as info:
                self.pg.locator('[data-testid="co-submit"]').click()
            resp = info.value
            data = self._json(resp)
            status = resp.status
        except Exception as exc:  # noqa: BLE001
            rec = self._browser_step("submit_checkout", f"checkout did not complete: {type(exc).__name__}: {str(exc)[:160]}")
            self._shot(rec)
            self.halt("checkout form did not respond")
            return
        rec = self._browser_step("submit_checkout", f"submit checkout form ({self.payment}) -> {status}", status)
        self._shot(rec)
        code = data.get("error_code") if isinstance(data, dict) else None
        self.checkout_outcome(rec, status, code, data)

    def act_confirm_order(self) -> None:
        self.confirmed = True
        status = self._goto(f"/order/confirmed/{self.order_id}")
        rec = self._browser_step("confirm_order", "open the order confirmation page", status)
        self._shot(rec)
