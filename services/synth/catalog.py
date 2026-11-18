"""Read-only view of the store catalog (apps/store/data/catalog.json) with a tiny built-in fallback."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentlens import settings

CATALOG_FILE = settings.REPO_ROOT / "apps" / "store" / "data" / "catalog.json"
CATEGORIES = ("mens-sneakers", "womens-kurtas", "mens-shirts", "accessories")


def _fallback() -> list[dict[str, Any]]:
    rng = random.Random(7)
    out = []
    for ci, cat in enumerate(CATEGORIES):
        for i in range(15):
            sizes = ["UK 7", "UK 8", "UK 9", "UK 10"] if cat == "mens-sneakers" else ["S", "M", "L", "XL"]
            out.append(
                {
                    "id": f"{cat[:3].upper()}{ci}{i:02d}", "slug": f"{cat}-item-{i}", "category": cat,
                    "price": 799 + rng.randrange(0, 3500), "price_mismatch": i == 3 and ci == 1, "cart_price": None,
                    "variants": [
                        {"sku": f"{cat}-{i}-{s}", "size": s, "colour": "Navy", "stock": 0 if rng.random() < 0.1 else 10}
                        for s in sizes
                    ],
                }
            )
    return out


@dataclass
class Catalog:
    products: list[dict[str, Any]]

    @classmethod
    def load(cls, path: Path | None = None) -> Catalog:
        p = path or CATALOG_FILE
        if p.exists():
            doc = json.loads(p.read_text(encoding="utf-8"))
            products = doc["products"] if isinstance(doc, dict) else doc
        else:
            products = _fallback()
        cat = cls(products)
        cat._by_id = {x["id"]: x for x in products}
        cat._by_cat = {c: [x for x in products if x["category"] == c] for c in {x["category"] for x in products}}
        return cat

    _by_id: dict[str, dict[str, Any]] = None  # type: ignore[assignment]
    _by_cat: dict[str, list[dict[str, Any]]] = None  # type: ignore[assignment]

    def get(self, product_id: str) -> dict[str, Any] | None:
        return self._by_id.get(product_id)

    def by_slug(self, slug: str) -> dict[str, Any] | None:
        return next((p for p in self.products if p["slug"] == slug), None)

    def in_category(self, category: str) -> list[dict[str, Any]]:
        return self._by_cat.get(category, [])

    @property
    def categories(self) -> list[str]:
        return sorted(self._by_cat)

    def pick(self, rng: random.Random, category: str | None = None) -> dict[str, Any]:
        pool = self.in_category(category) if category else self.products
        return rng.choice(pool or self.products)

    def cheapest(self, category: str) -> dict[str, Any]:
        return min(self.in_category(category) or self.products, key=lambda p: p["price"])
