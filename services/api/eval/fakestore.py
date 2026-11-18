"""A stand-in for the demo store's public pages, driven by the same friction toggles as the synth generator.

Used by the golden-set evaluation so the site checks (robots, SSR price, JSON-LD, size guide, captcha) run through the real
probing code against an in-process `httpx.MockTransport`, with no network. It mirrors what the store renders per toggle:
F14 robots disallow, F03 JS-only price, F04 missing/partial JSON-LD, F09 image-only size guide, F02 captcha endpoint.
"""

from __future__ import annotations

import json

import httpx

AI_TOKENS = [
    "GPTBot", "ChatGPT-User", "OAI-SearchBot", "ClaudeBot", "Claude-User", "Claude-SearchBot", "PerplexityBot",
    "Perplexity-User", "Google-Extended", "Applebot-Extended", "CCBot", "Bytespider", "meta-externalagent", "TestSignedAgent",
]  # fmt: skip


def robots_txt(blocked: bool) -> str:
    lines = ["User-agent: *", "Allow: /", ""]
    if blocked:
        for tok in AI_TOKENS:
            lines += [f"User-agent: {tok}", "Disallow: /p/", ""]
    lines.append("Sitemap: https://store.example/sitemap.xml")
    return "\n".join(lines)


def pdp_html(*, ssr_price: bool, jsonld: str) -> str:
    """jsonld: 'full' (Product with offer), 'basic' (Product without offer) or 'none'."""
    ld = ""
    if jsonld == "full":
        doc = {"@context": "https://schema.org", "@type": "Product", "name": "Sneaker", "offers": {"@type": "Offer", "price": "2999", "priceCurrency": "INR"}}
        ld = f'<script type="application/ld+json">{json.dumps(doc)}</script>'
    elif jsonld == "basic":
        ld = '<script type="application/ld+json">{"@type": "Product", "name": "Sneaker"}</script>'
    price = '<span class="price">₹2,999</span>' if ssr_price else '<div id="root"></div><script>render({"price": "₹2,999"})</script>'
    return f"<html><head>{ld}</head><body><h1>Sneaker</h1>{price}</body></html>"


def store_transport(active: set[str]) -> httpx.MockTransport:
    """`active` = set of friction ids such as {"F03", "F09"}."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text=robots_txt("F14" in active))
        if path.startswith("/p/"):
            if path.endswith("-old"):
                return httpx.Response(404, text="not found")
            return httpx.Response(200, html=pdp_html(ssr_price="F03" not in active, jsonld="none" if "F04" in active else "full"))
        if path.startswith("/size-guide/"):
            body = "<img src='/img/size-chart.png' alt='Size chart'>" if "F09" in active else "<table data-testid='size-table'><tr><td>UK 9</td></tr></table>"
            return httpx.Response(200, html=f"<html><body>{body}</body></html>")
        if path == "/api/captcha":
            return httpx.Response(200, json={"challenge": "x"}) if "F02" in active else httpx.Response(404, json={})
        if path == "/sitemap.xml":
            return httpx.Response(200, text="<urlset/>")
        return httpx.Response(404, text="not found")

    return httpx.MockTransport(handler)
