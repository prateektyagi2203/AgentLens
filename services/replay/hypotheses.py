"""Blocker hypotheses the replay agent can test.

To add one: add an entry here, make the matching journey action emit `Journey.signal("Bxx", present, detail, step)` (see
docs/replay-agent.md), and, if it needs a probe that the normal journey does not run, add it to `Journey.allowed`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Hypothesis:
    blocker_id: str
    friction: str | None          # store toggle that produces it in the demo store
    modes: tuple[str, ...]        # modes that can observe it
    stage: str
    summary: str
    inconclusive_hint: str


HYPOTHESES: dict[str, Hypothesis] = {
    h.blocker_id: h
    for h in [
        Hypothesis("B01", "F01", ("fetch", "browser"), "any", "A bot wall blocks non-browser clients",
                   "the control probe did not run"),
        Hypothesis("B02", "F02", ("fetch", "browser"), "S6/S7", "A captcha guards checkout submission",
                   "the journey never reached checkout submission"),
        Hypothesis("B03", "F03", ("fetch", "browser"), "S2", "Price/stock exist only after client-side JS",
                   "no product page was fetched"),
        Hypothesis("B04", "F04", ("fetch", "browser"), "S2", "Product pages carry no JSON-LD",
                   "no product page was fetched"),
        Hypothesis("B05", "F05", ("fetch", "browser"), "S4/S5", "Add to cart is gated by a pincode check",
                   "the journey never reached add-to-cart"),
        Hypothesis("B06", "F06", ("fetch", "browser"), "S5", "Add to cart requires an OTP login",
                   "the journey never reached add-to-cart"),
        Hypothesis("B07", "F07/F08", ("browser",), "S1/S2", "A full-screen overlay covers the page",
                   "overlays are rendered client-side and only a browser replay can see them"),
        Hypothesis("B08", "F16", ("fetch", "browser"), "S3", "An out-of-stock variant is a dead end",
                   "no out-of-stock variant was encountered among the candidate products"),
        Hypothesis("B09", "F09", ("fetch", "browser"), "S3", "The size guide is an image with no HTML table",
                   "the size guide page was not fetched"),
        Hypothesis("B10", "F10", ("fetch", "browser"), "S7", "Checkout rejects a plain 10-digit phone number",
                   "the journey never reached checkout submission"),
        Hypothesis("B11", "F15", ("fetch", "browser"), "S7", "COD orders need an extra OTP step",
                   "the journey never reached checkout submission with cash on delivery"),
        Hypothesis("B12", "F12", ("fetch",), "any", "Bursts of requests are rate limited",
                   "the rate-limit probe was skipped (it only runs against local test hosts or with load_probes)"),
        Hypothesis("B13", "F13", ("fetch", "browser"), "any", "Product pages respond slowly",
                   "no product page was fetched"),
        Hypothesis("B14", "F14", ("fetch", "browser"), "S1/S2", "robots.txt disallows listed AI agents",
                   "robots.txt was not read"),
        Hypothesis("B15", "F11", ("fetch", "browser"), "S5/S6", "Cart price differs from the product page price",
                   "no item was added to the cart"),
        Hypothesis("B16", None, ("fetch", "browser"), "any", "Internal links lead to 404 pages",
                   "the link check did not run"),
    ]
}

# Hypotheses that need a real DOM; the runner upgrades these to browser mode when Chromium is available.
BROWSER_ONLY = {k for k, h in HYPOTHESES.items() if h.modes == ("browser",)}
