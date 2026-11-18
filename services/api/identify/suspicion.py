"""Tier 3 (Suspected): weighted behavioural suspicion score from per-client-run features (PRD 11.3).

Features are aggregated set-based in DuckDB (see engine.py); this module is the pure scoring rule so each signal
can be unit-tested in isolation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

HEADLESS_RE = re.compile(r"headless|phantomjs|selenium|webdriver|puppeteer|playwright", re.I)
HEADLESS_SQL = "headless|phantomjs|selenium|webdriver|puppeteer|playwright"

DEFAULT_WEIGHTS = {
    "no_beacon_with_browser_ua": 25,
    "no_assets": 15,
    "headless_hint": 30,
    "missing_sec_fetch": 10,
    "regular_timing": 10,
    "high_velocity": 10,
    "deep_link_cart_rush": 5,
    "atypical_accept": 5,
    "invalid_signature": 30,
}


@dataclass
class RunFeatures:
    """Behavioural summary of one client run (a client's requests with no gap above the session timeout)."""

    n_html: int = 0  # HTML page requests
    n_assets: int = 0
    n_beacons: int = 0
    n_pagelike: int = 0  # non-asset, non-beacon requests (pages and API calls)
    ua_browser: bool = False  # UA claims a full browser (and is not a declared agent token)
    ua_modern: bool = False
    headless_hint: bool = False
    html_missing_sec_fetch: int = 0
    gap_cv: float | None = None
    n_gaps: int = 0
    pages_per_min: float | None = None
    deep_link_cart_rush: bool = False
    atypical_accept_frac: float = 0.0
    invalid_signature: bool = False


@dataclass
class SuspicionConfig:
    threshold: float = 60
    page_velocity_per_min: float = 15
    regular_timing_cv: float = 0.25
    regular_timing_min_gaps: int = 4
    velocity_min_pages: int = 5
    weights: dict[str, float] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.weights = {**DEFAULT_WEIGHTS, **(self.weights or {})}

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> SuspicionConfig:
        s = cfg.get("suspicion", {})
        return cls(
            threshold=s.get("threshold", 60),
            page_velocity_per_min=s.get("page_velocity_per_min", 15),
            regular_timing_cv=s.get("regular_timing_cv", 0.25),
            regular_timing_min_gaps=s.get("regular_timing_min_gaps", 4),
            velocity_min_pages=s.get("velocity_min_pages", 5),
            weights=s.get("weights"),
        )


def score_signals(f: RunFeatures, cfg: SuspicionConfig) -> dict[str, float]:
    """Return {signal: weight} for every signal that fired."""
    w = cfg.weights
    fired: dict[str, float] = {}
    if f.n_html >= 1 and f.ua_browser and f.n_beacons == 0:
        fired["no_beacon_with_browser_ua"] = w["no_beacon_with_browser_ua"]
    if f.n_html >= 1 and f.n_assets == 0:
        fired["no_assets"] = w["no_assets"]
    if f.headless_hint:
        fired["headless_hint"] = w["headless_hint"]
    if f.ua_modern and f.n_html >= 1 and f.html_missing_sec_fetch >= f.n_html:
        fired["missing_sec_fetch"] = w["missing_sec_fetch"]
    if f.gap_cv is not None and f.n_gaps >= cfg.regular_timing_min_gaps and f.gap_cv < cfg.regular_timing_cv:
        fired["regular_timing"] = w["regular_timing"]
    if (
        f.pages_per_min is not None
        and f.n_pagelike >= cfg.velocity_min_pages
        and f.pages_per_min > cfg.page_velocity_per_min
    ):
        fired["high_velocity"] = w["high_velocity"]
    if f.deep_link_cart_rush:
        fired["deep_link_cart_rush"] = w["deep_link_cart_rush"]
    if f.ua_browser and f.n_html >= 1 and f.atypical_accept_frac > 0.5:
        fired["atypical_accept"] = w["atypical_accept"]
    if f.invalid_signature:
        fired["invalid_signature"] = w["invalid_signature"]
    return fired


def suspicion_score(f: RunFeatures, cfg: SuspicionConfig) -> float:
    return min(100.0, sum(score_signals(f, cfg).values()))
