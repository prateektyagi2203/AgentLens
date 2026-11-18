"""Task parsing: free-text shopping goal -> structured spec (size, colour, budget, pincode, query)."""

from __future__ import annotations

import re
from dataclasses import dataclass

COLOURS = ("blue", "black", "white", "red", "green", "grey", "gray", "navy", "maroon", "beige", "olive", "pink", "yellow")
CATEGORY_WORDS = ("shirt", "kurta", "sneaker", "shoe", "belt", "wallet", "watch", "bag", "scarf", "cap")


@dataclass(frozen=True)
class TaskSpec:
    text: str
    size: str | None
    colour: str | None
    category: str | None
    max_price: int | None
    pincode: str | None
    query: str

    def describe(self) -> str:
        bits = [f"size {self.size}" if self.size else "", self.colour or "", self.category or "",
                f"<= INR {self.max_price}" if self.max_price else "", f"pin {self.pincode}" if self.pincode else ""]  # fmt: skip
        return " ".join(b for b in bits if b)


def parse_task(text: str) -> TaskSpec:
    low = text.lower()
    size_m = re.search(r"\bsize[\s-]*(xxl|xl|xs|s|m|l|\d{1,2})\b", low) or re.search(r"\b(xxl|xl|xs)\b", low)
    price_m = re.search(r"(?:under|below|within|upto|up to|<=?)\s*(?:rs\.?|inr|₹)?\s*([\d,]+)", low) or re.search(
        r"(?:rs\.?|inr|₹)\s*([\d,]+)", low
    )
    pin_m = re.search(r"\b([1-8]\d{5})\b", low)
    colour = next((c for c in COLOURS if re.search(rf"\b{c}\b", low)), None)
    category = next((c for c in CATEGORY_WORDS if re.search(rf"\b{c}s?\b", low)), None)
    query = " ".join(x for x in (colour, category) if x) or "shirt"
    return TaskSpec(
        text=text,
        size=size_m.group(1).upper() if size_m else None,
        colour=colour,
        category=category,
        max_price=int(price_m.group(1).replace(",", "")) if price_m else None,
        pincode=pin_m.group(1) if pin_m else None,
        query=query,
    )
