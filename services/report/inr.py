"""Indian rupee formatting: lakh / crore short form (₹12.6 L, ₹1.2 Cr) and en-IN digit grouping (₹82,400)."""

from __future__ import annotations

LAKH = 100_000
CRORE = 10_000_000


def _trim1(x: float) -> str:
    s = f"{x:.1f}"
    return s[:-2] if s.endswith(".0") else s


def group_in(n: int) -> str:
    """12345678 -> '1,23,45,678' (en-IN grouping)."""
    s = str(abs(int(n)))
    if len(s) <= 3:
        out = s
    else:
        head, tail = s[:-3], s[-3:]
        parts: list[str] = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        out = ",".join([*parts, tail])
    return ("-" if n < 0 else "") + out


def inr(value: float | None) -> str:
    """Short form used for headline numbers: ₹12.6 L, ₹1.2 Cr, ₹82,400. None renders as an em dash."""
    if value is None or value != value:
        return "—"
    sign = "-" if value < 0 else ""
    a = abs(value)
    if a >= CRORE:
        return f"{sign}₹{_trim1(a / CRORE)} Cr"
    if a >= LAKH:
        lakhs = float(_trim1(a / LAKH))
        if lakhs >= 100:
            return f"{sign}₹{_trim1(a / CRORE)} Cr"
        return f"{sign}₹{_trim1(a / LAKH)} L"
    return f"{sign}₹{group_in(round(a))}"


def inr_full(value: float | None) -> str:
    """Exact rupees with en-IN grouping: ₹12,63,000."""
    if value is None or value != value:
        return "—"
    return f"{'-' if value < 0 else ''}₹{group_in(round(abs(value)))}"


def inr_range(low: float, high: float) -> str:
    return f"{inr(low)} to {inr(high)}"


def pct(x: float | None, digits: int = 1) -> str:
    return "—" if x is None or x != x else f"{x * 100:.{digits}f}%"
