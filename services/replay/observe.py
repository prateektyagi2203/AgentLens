"""Stdlib HTML observation helpers: JSON-LD, data-testid markers, links, prices, forms. No third-party parser."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from typing import Any

_LD = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)
_TESTID = re.compile(r'data-testid="([^"]+)"')
_LINK = re.compile(r'<a\b[^>]*?href="([^"#]+)"', re.I)
_PRICE = re.compile(r"₹\s*([\d,]+)")
_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)


def json_ld(markup: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in _LD.findall(markup):
        try:
            data = json.loads(html.unescape(raw) if "&quot;" in raw else raw)
        except ValueError:
            continue
        items = data if isinstance(data, list) else [data]
        out.extend(i for i in items if isinstance(i, dict))
    return out


def testids(markup: str) -> set[str]:
    return set(_TESTID.findall(markup))


def product_links(markup: str) -> list[str]:
    seen: list[str] = []
    for href in _LINK.findall(markup):
        if href.startswith("/p/") and href not in seen:
            seen.append(href)
    return seen


def visible_text(markup: str, limit: int = 4000) -> str:
    text = html.unescape(_TAG.sub(" ", _SCRIPT.sub(" ", markup)))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def inr(value: str) -> int:
    return int(value.replace(",", ""))


def card_prices(markup: str) -> dict[str, int]:
    """Search-result cards: product path -> first ₹ amount inside the card."""
    out: dict[str, int] = {}
    for m in re.finditer(r'<a\b[^>]*?href="(/p/[^"]+)"[^>]*>(.*?)</a>', markup, re.S):
        price = _PRICE.search(m.group(2))
        if price and m.group(1) not in out:
            out[m.group(1)] = inr(price.group(1))
    return out


@dataclass
class ProductPage:
    slug: str
    name: str | None = None
    sku: str | None = None
    has_json_ld: bool = False
    server_price: int | None = None
    price_source: str | None = None        # json-ld | dom | None (client-side only)
    client_price_only: bool = False
    in_stock_hint: bool | None = None
    sizes: list[str] = field(default_factory=list)
    colours: list[str] = field(default_factory=list)
    pincode_modal: bool = False
    variants_ld: list[dict[str, Any]] = field(default_factory=list)


def parse_product_page(slug: str, markup: str) -> ProductPage:
    page = ProductPage(slug=slug)
    for item in json_ld(markup):
        if item.get("@type") == "Product":
            page.has_json_ld = True
            page.name = item.get("name")
            page.sku = item.get("sku")
            offers = item.get("offers")
            if isinstance(offers, dict) and offers.get("price") is not None:
                page.server_price, page.price_source = int(float(offers["price"])), "json-ld"
                page.in_stock_hint = "InStock" in str(offers.get("availability", ""))
            variants = item.get("hasVariant")
            if isinstance(variants, list):
                page.variants_ld = [v for v in variants if isinstance(v, dict)]
    ids = testids(markup)
    if page.server_price is None and "price" in ids:
        m = re.search(r'data-testid="price"[^>]*>(.*?)</', markup, re.S)
        amount = _PRICE.search(html.unescape(_TAG.sub("", m.group(1)))) if m else None
        if amount:
            page.server_price, page.price_source = inr(amount.group(1)), "dom"
    page.client_price_only = page.server_price is None and ("client-price" in ids or "price" not in ids)
    page.sizes = [i[5:] for i in sorted(ids) if i.startswith("size-")]
    page.colours = [i[7:] for i in sorted(ids) if i.startswith("colour-")]
    page.pincode_modal = "pincode-modal" in ids
    if page.name is None:
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", markup, re.S)
        page.name = html.unescape(_TAG.sub("", h1.group(1))).strip() if h1 else None
    return page


def size_guide_has_table(markup: str) -> bool:
    return "size-table" in testids(markup) or "<table" in markup


def size_guide_has_image(markup: str) -> bool:
    return bool(re.search(r"<img\b[^>]*/img/size/", markup))
