"""Render the report HTML to PDF and PNG with Playwright's Chromium (already a dependency; no system installs)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


class RendererUnavailable(RuntimeError):
    """Chromium cannot be launched (run `python -m playwright install chromium`)."""


def chromium_ready() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        def probe() -> bool:
            with sync_playwright() as p:
                return Path(p.chromium.executable_path).exists()

        with ThreadPoolExecutor(1) as ex:
            return ex.submit(probe).result()
    except Exception:  # noqa: BLE001 - any failure means the renderer cannot be used
        return False


def _render(html: str, want_pdf: bool, want_png: bool) -> tuple[bytes | None, bytes | None]:
    from playwright.sync_api import sync_playwright

    pdf = png = None
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            raise RendererUnavailable(
                f"Chromium is not available ({type(exc).__name__}). Run: python -m playwright install chromium"
            ) from exc
        try:
            page = browser.new_page(viewport={"width": 794, "height": 1123}, device_scale_factor=2)
            page.route("**/*", lambda route: route.abort() if route.request.url.startswith("http") else route.continue_())
            page.set_content(html, wait_until="load")
            if want_pdf:
                pdf = page.pdf(format="A4", print_background=True, prefer_css_page_size=True)
            if want_png:
                png = page.locator("#page1").screenshot(type="png")
        finally:
            browser.close()
    return pdf, png


def render_pdf_png(html: str, *, pdf: bool = True, png: bool = True) -> tuple[bytes | None, bytes | None]:
    """Run in a worker thread so it also works when called from inside an asyncio loop (the API)."""
    with ThreadPoolExecutor(1) as ex:
        return ex.submit(_render, html, pdf, png).result()
