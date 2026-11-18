"""page_type classification from config/funnel.yaml `page_types` (first match wins, default `other`)."""

from __future__ import annotations

import re
from typing import Any

from .. import settings

DEFAULT_PAGE_TYPE = "other"
# Types that are neither pages nor API calls a shopper "visits": excluded from page counts.
NON_PAGE_TYPES = ("asset", "beacon")


def load_rules(funnel_cfg: dict[str, Any] | None = None) -> list[tuple[str, str]]:
    cfg = funnel_cfg if funnel_cfg is not None else settings.load_yaml("funnel")
    return [(r["type"], r["path"]) for r in cfg.get("page_types", [])]


def classify_path(path: str, rules: list[tuple[str, str]]) -> str:
    for ptype, pattern in rules:
        if re.search(pattern, path):
            return ptype
    return DEFAULT_PAGE_TYPE


def _lit(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def path_type_sql(rules: list[tuple[str, str]], path_col: str = "path") -> str:
    """Set-based CASE expression equivalent to classify_path (DuckDB RE2 regexes)."""
    whens = " ".join(
        f"WHEN regexp_matches({path_col}, {_lit(pattern)}) THEN {_lit(ptype)}" for ptype, pattern in rules
    )
    return f"CASE {whens} ELSE {_lit(DEFAULT_PAGE_TYPE)} END"


def page_type_sql(rules: list[tuple[str, str]], path_col: str = "path") -> str:
    """Like path_type_sql but beacons and flagged assets win over the path patterns."""
    return (
        f"CASE WHEN event_type = 'beacon' THEN 'beacon' WHEN is_asset THEN 'asset' "
        f"ELSE {path_type_sql(rules, path_col)} END"
    )
