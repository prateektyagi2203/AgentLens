"""Blocker rules B01-B16 (PRD 12.4) as set-based SQL. One function per blocker, registered with `@rule`.

Every rule returns a SELECT with exactly these columns (one row per session and blocker):

    session_id, blocker_id, stage_id, confidence, evidence_ts, ev_ids VARCHAR[], site_ev VARCHAR[], note VARCHAR

`ev_ids` are request ids shown as evidence, `site_ev` holds `"<check>=<result>"` strings for the site checks that
confirmed or contradicted the rule, `note` is an optional sentence appended to the first evidence request.

Rules only emit *unresolved* failures: a failure followed by a success on the same endpoint (the agent got past it)
is not a blocker. Tables available to a rule (built by `engine.py`, scoped to diagnosable sessions):

    _dsess  session_id, start_ts, tier, agent_class, agent_name, has_beacon, shop, ok_cart_ts, ok_checkout_ts,
            saw_captcha, saw_login, last_variant_ts
    _dreq   request_id, session_id, ts, rn, rn_desc (1 = last), method, path, query, status, error_code, duration_ms,
            page_type, bytes_out, unit_price, product_id, stage_id         (meaningful requests only: no assets/beacons)
    _dsite  session_id, pdp_ssr_price, pdp_jsonld_product, size_guide_table, captcha_presence, robots_txt,
            robots_blocked VARCHAR[]                    (site-check results valid at the session's start; NULL = unknown)
    _dcat   product_id, size, colour, stock, price      (catalog snapshot; empty when unavailable)

To add a blocker: write a function decorated with `@rule("B17", "title", shop_only=True)` that returns such a SELECT,
add B17 to config/blockers.yaml, and add positive/negative cases to tests/python/test_diagnosis_rules.py.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

NO_EVIDENCE = "CAST([] AS VARCHAR[])"
EPOCH = "TIMESTAMP '1970-01-01'"

RuleSql = Callable[[dict[str, Any]], str]


@dataclass(frozen=True)
class Rule:
    blocker_id: str
    title: str
    sql: RuleSql
    shop_only: bool  # True: skip crawler sessions (they only get the infrastructure rules)


RULES: dict[str, Rule] = {}


def rule(blocker_id: str, title: str, *, shop_only: bool = True) -> Callable[[RuleSql], RuleSql]:
    def deco(fn: RuleSql) -> RuleSql:
        RULES[blocker_id] = Rule(blocker_id, title, fn, shop_only)
        return fn

    return deco


def _code_failure(
    blocker: str, stage: str, page_type: str, method: str, cond: str, conf: str, ok_col: str, *,
    site_ev: str = NO_EVIDENCE,
) -> str:  # fmt: skip
    """An error response on one endpoint that was never followed by a success on that endpoint."""
    return f"""
        SELECT r.session_id, '{blocker}' AS blocker_id, '{stage}' AS stage_id, max({conf}) AS confidence,
               max(r.ts) AS evidence_ts, (list(r.request_id ORDER BY r.ts DESC))[1:3] AS ev_ids,
               any_value({site_ev}) AS site_ev, CAST(NULL AS VARCHAR) AS note
        FROM _dreq r JOIN _dsess s USING (session_id) LEFT JOIN _dsite st USING (session_id)
        WHERE s.shop AND r.page_type = '{page_type}' AND r.method = '{method}' AND ({cond})
          AND r.ts > COALESCE(s.{ok_col}, {EPOCH})
        GROUP BY r.session_id
    """


# ---- infrastructure rules (also applied to crawlers) --------------------------------------------------------------

@rule("B01", "Bot wall / WAF block", shop_only=False)
def b01(cfg: dict[str, Any]) -> str:
    return f"""
        SELECT r.session_id, 'B01', r.stage_id, CASE WHEN r.error_code = 'BOT_CHALLENGE' THEN 0.95 ELSE 0.7 END,
               r.ts, [r.request_id], {NO_EVIDENCE}, CAST(NULL AS VARCHAR)
        FROM _dreq r
        WHERE r.rn_desc = 1 AND r.status IN (403, 503) AND (r.error_code = 'BOT_CHALLENGE' OR r.error_code IS NULL)
    """


@rule("B12", "Rate limited", shop_only=False)
def b12(cfg: dict[str, Any]) -> str:
    return f"""
        SELECT r.session_id, 'B12', r.stage_id, CASE WHEN r.error_code = 'RATE_LIMITED' THEN 0.95 ELSE 0.85 END,
               r.ts, [r.request_id], {NO_EVIDENCE}, CAST(NULL AS VARCHAR)
        FROM _dreq r WHERE r.rn_desc = 1 AND r.status = 429
    """


@rule("B13", "Slow response / timeout", shop_only=False)
def b13(cfg: dict[str, Any]) -> str:
    slow = int(cfg["thresholds"]["slow_ms"])
    return f"""
        SELECT r.session_id, 'B13', r.stage_id, 0.9, r.ts, [r.request_id], {NO_EVIDENCE},
               'responded in ' || r.duration_ms || ' ms (threshold {slow} ms)'
        FROM _dreq r WHERE r.rn_desc = 1 AND r.duration_ms > {slow} AND COALESCE(r.status, 200) < 400
    """


@rule("B16", "Broken link / 404", shop_only=False)
def b16(cfg: dict[str, Any]) -> str:
    return f"""
        SELECT r.session_id, 'B16', r.stage_id, 0.95, r.ts, [r.request_id], {NO_EVIDENCE}, CAST(NULL AS VARCHAR)
        FROM _dreq r
        WHERE r.rn_desc = 1 AND r.status = 404
          AND r.page_type IN ('pdp', 'plp', 'cart', 'checkout', 'order_confirm', 'size_guide')
    """


# ---- cart / checkout walls: explicit error codes from the log contract -------------------------------------------

@rule("B05", "Pincode / serviceability wall")
def b05(cfg: dict[str, Any]) -> str:
    return _code_failure(
        "B05", "S5", "cart_api", "POST", "r.status = 409 AND r.error_code = 'PINCODE_REQUIRED'", "0.95", "ok_cart_ts"
    )


@rule("B06", "Login / OTP wall before cart")
def b06(cfg: dict[str, Any]) -> str:
    return _code_failure(
        "B06", "S5", "cart_api", "POST", "r.status = 401",
        "CASE WHEN r.error_code = 'AUTH_REQUIRED' THEN CASE WHEN s.saw_login THEN 0.97 ELSE 0.95 END ELSE 0.7 END",
        "ok_cart_ts",
    )  # fmt: skip


@rule("B02", "Captcha at checkout")
def b02(cfg: dict[str, Any]) -> str:
    return _code_failure(
        "B02", "S7", "checkout_api", "POST", "r.status = 403 AND r.error_code = 'CAPTCHA_REQUIRED'",
        "CASE WHEN s.saw_captcha OR st.captcha_presence = 'fail' THEN 0.97 ELSE 0.92 END", "ok_checkout_ts",
        site_ev="CASE WHEN st.captcha_presence IS NULL THEN CAST([] AS VARCHAR[]) ELSE ['captcha_presence=' || st.captcha_presence] END",
    )  # fmt: skip


@rule("B10", "Checkout validation failure")
def b10(cfg: dict[str, Any]) -> str:
    return _code_failure(
        "B10", "S7", "checkout_api", "POST", "r.status IN (400, 422)",
        "CASE WHEN r.error_code = 'PHONE_FORMAT' THEN 0.95 ELSE 0.65 END", "ok_checkout_ts",
    )  # fmt: skip


@rule("B11", "Unsupported payment step")
def b11(cfg: dict[str, Any]) -> str:
    return _code_failure(
        "B11", "S7", "checkout_api", "POST", "r.status = 409 AND r.error_code = 'COD_OTP_REQUIRED'", "0.95", "ok_checkout_ts"
    )


@rule("B08", "Out-of-stock dead end")
def b08(cfg: dict[str, Any]) -> str:
    """409 OUT_OF_STOCK on the variants API or the cart, or a 200 variants answer for a size the catalog shows empty.
    A variants failure counts only if the agent did not look at another variant afterwards."""
    return f"""
        WITH v AS (
          SELECT r.session_id, r.request_id, r.ts, r.page_type = 'variant_api' AS is_var,
                 CASE WHEN r.page_type = 'variant_api' AND r.status = 409 AND r.error_code = 'OUT_OF_STOCK' THEN 0.95
                      WHEN r.page_type = 'cart_api' AND r.status = 409 AND r.error_code = 'OUT_OF_STOCK' THEN 0.9
                      WHEN r.page_type = 'variant_api' AND r.status = 200 AND c.stock <= 0 THEN 0.8 END AS conf,
                 CASE WHEN r.status = 200 AND c.stock <= 0 THEN 'catalog shows 0 in stock for this size and colour' END AS note
          FROM _dreq r JOIN _dsess s USING (session_id)
          LEFT JOIN _dcat c ON c.product_id = regexp_extract(r.path, '^/api/products/([^/]+)/variants', 1)
               AND c.size = lower(replace(replace(regexp_extract(r.query, 'size=([^&]*)', 1), '+', ' '), '%20', ' '))
               AND c.colour = lower(replace(replace(regexp_extract(r.query, 'colour=([^&]*)', 1), '+', ' '), '%20', ' '))
          WHERE s.shop AND r.ts > COALESCE(s.ok_cart_ts, {EPOCH})
            AND (r.page_type = 'variant_api' OR (r.page_type = 'cart_api' AND r.method = 'POST'))
        )
        SELECT v.session_id, 'B08', 'S3', max(v.conf), max(v.ts), (list(v.request_id ORDER BY v.ts DESC))[1:3],
               {NO_EVIDENCE}, any_value(v.note)
        FROM v JOIN _dsess s USING (session_id)
        WHERE v.conf IS NOT NULL AND (NOT v.is_var OR v.ts >= COALESCE(s.last_variant_ts, {EPOCH}))
        GROUP BY v.session_id
    """


# ---- content rules: need a site check to be confirmed ------------------------------------------------------------

@rule("B09", "Size guide is image-only")
def b09(cfg: dict[str, Any]) -> str:
    return f"""
        SELECT r.session_id, 'B09', 'S3',
               CASE st.size_guide_table WHEN 'fail' THEN 0.85 WHEN 'pass' THEN 0.2 ELSE 0.45 END,
               r.ts, [r.request_id],
               CASE WHEN st.size_guide_table IS NULL THEN {NO_EVIDENCE} ELSE ['size_guide_table=' || st.size_guide_table] END,
               CAST(NULL AS VARCHAR)
        FROM _dreq r JOIN _dsess s USING (session_id) LEFT JOIN _dsite st USING (session_id)
        WHERE s.shop AND r.rn_desc = 1 AND r.page_type = 'size_guide' AND r.status = 200
    """


def _last_pdp(extra_cond: str, blocker: str, conf: str, site_ev: str) -> str:
    return f"""
        SELECT r.session_id, '{blocker}', 'S2', {conf}, r.ts, [r.request_id], {site_ev}, CAST(NULL AS VARCHAR)
        FROM _dreq r JOIN _dsess s USING (session_id) LEFT JOIN _dsite st USING (session_id)
        WHERE s.shop AND r.rn_desc = 1 AND r.page_type = 'pdp' AND r.status = 200 AND {extra_cond}
    """


@rule("B03", "JS-only product content")
def b03(cfg: dict[str, Any]) -> str:
    return _last_pdp(
        "NOT s.has_beacon AND s.agent_class = 'user_fetcher'", "B03",
        "CASE st.pdp_ssr_price WHEN 'fail' THEN 0.85 WHEN 'pass' THEN 0.1 ELSE 0.4 END",
        "CASE WHEN st.pdp_ssr_price IS NULL THEN CAST([] AS VARCHAR[]) ELSE ['pdp_ssr_price=' || st.pdp_ssr_price] END",
    )


@rule("B04", "Missing structured data")
def b04(cfg: dict[str, Any]) -> str:
    return _last_pdp(
        "NOT s.has_beacon AND s.agent_class = 'user_fetcher'", "B04",
        "CASE st.pdp_jsonld_product WHEN 'fail' THEN 0.8 WHEN 'warn' THEN 0.6 WHEN 'pass' THEN 0.1 ELSE 0.4 END",
        "CASE WHEN st.pdp_jsonld_product IS NULL THEN CAST([] AS VARCHAR[]) ELSE ['pdp_jsonld_product=' || st.pdp_jsonld_product] END",
    )


@rule("B07", "Interstitial / popup overlay")
def b07(cfg: dict[str, Any]) -> str:
    """A browsing agent (runs JS) that stops on a product page it loaded fine: nothing server-side explains it.
    Needs a replay to confirm (PRD 12.4), so the confidence stays low."""
    return _last_pdp(
        "s.agent_class = 'browsing_agent'", "B07", "CASE WHEN s.has_beacon THEN 0.6 ELSE 0.5 END", NO_EVIDENCE
    )


@rule("B14", "robots.txt disallow")
def b14(cfg: dict[str, Any]) -> str:
    return f"""
        SELECT r.session_id, 'B14', 'S2',
               CASE WHEN st.robots_blocked IS NULL THEN 0.7
                    WHEN list_contains(st.robots_blocked, lower(s.agent_name)) THEN 0.9 ELSE 0.3 END,
               r.ts, [r.request_id],
               CASE WHEN st.robots_txt IS NULL THEN {NO_EVIDENCE} ELSE ['robots_txt=' || st.robots_txt] END,
               CASE WHEN st.robots_blocked IS NOT NULL AND list_contains(st.robots_blocked, lower(s.agent_name))
                    THEN s.agent_name || ' is disallowed from /p/ in robots.txt' END
        FROM _dreq r JOIN _dsess s USING (session_id) LEFT JOIN _dsite st USING (session_id)
        WHERE s.shop AND r.rn_desc = 1 AND r.page_type = 'robots' AND s.agent_class IN ('user_fetcher', 'browsing_agent')
    """


@rule("B15", "Price mismatch (PDP vs cart)")
def b15(cfg: dict[str, Any]) -> str:
    return f"""
        SELECT r.session_id, 'B15', 'S5', 0.85, r.ts, [r.request_id], {NO_EVIDENCE},
               'cart price ' || CAST(r.unit_price AS BIGINT) || ' vs catalog price ' || CAST(c.price AS BIGINT)
        FROM _dreq r JOIN _dsess s USING (session_id)
        JOIN (SELECT DISTINCT product_id, price FROM _dcat) c ON c.product_id = r.product_id
        WHERE s.shop AND r.rn_desc = 1 AND r.page_type = 'cart_api' AND r.method = 'POST' AND r.status = 201
          AND r.unit_price IS NOT NULL AND abs(r.unit_price - c.price) > 0.5
    """


def rule_sql(cfg: dict[str, Any], only: list[str] | None = None) -> dict[str, str]:
    return {bid: r.sql(cfg) for bid, r in sorted(RULES.items()) if only is None or bid in only}
