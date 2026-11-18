"""C4 identification engine (PRD 11): writes identity columns onto `requests`.

Order of evidence per request: Verified (Web Bot Auth) > Internal (replay) > Declared (UA token) >
Suspected (behavioural score) > Human. Verification is a Python loop over signed requests only; everything else is
set-based SQL. Results land in a temp table and are applied in one UPDATE (the pipeline wraps it in a transaction).
"""

from __future__ import annotations

from typing import Any

import duckdb
import pyarrow as pa

from .. import settings
from ..clientkey import keyed_sql
from .constants import (
    TIER_DECLARED,
    TIER_HUMAN,
    TIER_INTERNAL,
    TIER_SUSPECTED,
    TIER_VERIFIED,
)
from .keys import KeyResolver
from .signatures import FORGERY_STATUSES, VALID, RequestContext, default_scheme, verify_request
from .suspicion import HEADLESS_SQL, RunFeatures, SuspicionConfig, score_signals
from .ua_registry import (
    CLASS_BROWSING,
    CLASS_INTERNAL,
    UARegistry,
    declared_confidence,
)

HTML_TYPES = ("home", "plp", "search", "pdp", "cart", "login", "checkout", "order_confirm", "policy", "size_guide")
_HTML_SQL = ", ".join(f"'{t}'" for t in HTML_TYPES)
_FORGERY_SQL = ", ".join(f"'{s}'" for s in FORGERY_STATUSES)
RUN_GAP_MIN = 30


def _register(con: duckdb.DuckDBPyConnection, name: str, columns: dict[str, pa.DataType], rows: list[tuple[Any, ...]]) -> None:
    cols: list[Any] = list(zip(*rows, strict=True)) if rows else [[] for _ in columns]
    table = pa.Table.from_arrays(
        [pa.array(c, type=t) for c, t in zip(cols, columns.values(), strict=True)], names=list(columns)
    )
    con.register("_reg_tmp", table)
    try:
        con.execute(f"CREATE OR REPLACE TEMP TABLE {name} AS SELECT * FROM _reg_tmp")
    finally:
        con.unregister("_reg_tmp")


def _ua_map(con: duckdb.DuckDBPyConnection, reg: UARegistry) -> int:
    rows = []
    ua_rows = con.execute("SELECT DISTINCT ua_hash, user_agent FROM requests WHERE user_agent IS NOT NULL").fetchall()
    for ua_hash, ua in ua_rows:
        m = reg.match(ua)
        if m:
            tier = TIER_INTERNAL if m.agent_class == CLASS_INTERNAL else TIER_DECLARED
            rows.append((ua_hash, m.operator_key, m.operator, m.agent_name, m.agent_class, tier))
    s = pa.string()
    _register(con, "_ua_map", dict.fromkeys(("ua_hash", "operator_key", "operator", "agent_name", "agent_class", "tier"), s), rows)
    return len(rows)


def _ip_ok(con: duckdb.DuckDBPyConnection, reg: UARegistry) -> None:
    """(ua_hash, ip_prefix) pairs where a declared UA also comes from the operator's published ranges."""
    rows: list[tuple[str, str]] = []
    if any(reg.ip_ranges.values()):
        pairs = con.execute(
            "SELECT DISTINCT r.ua_hash, r.ip_prefix, m.operator_key FROM requests r "
            "JOIN _ua_map m USING (ua_hash) WHERE r.ip_prefix IS NOT NULL"
        ).fetchall()
        rows = [(h, ip, ) for h, ip, op in pairs if reg.ip_match(op, ip)]
    s = pa.string()
    _register(con, "_ip_ok", {"ua_hash": s, "ip_prefix": s}, rows)


def _verify_signed(con: duckdb.DuckDBPyConnection, reg: UARegistry, cfg: dict[str, Any]) -> dict[str, int]:
    sig_cfg = cfg.get("signature", {})
    resolver = KeyResolver(
        con,
        ttl_s=int(sig_cfg.get("key_cache_ttl_s", 3600)),
        offline=bool(sig_cfg.get("offline_mode", False)),
        overrides=sig_cfg.get("key_directory_overrides") or {},
    )
    skew = int(sig_cfg.get("clock_skew_s", 60))
    rows = con.execute(
        """
        SELECT r.request_id, r.ts, r.method, COALESCE(s.authority, r.host), COALESCE(s.path, r.path), r.query,
               r.user_agent, r.accept, r.accept_language, r.referer, r.sec_ch_ua, r.sec_fetch_site,
               r.sec_fetch_mode, r.sec_fetch_dest, s.signature, s.signature_input, s.signature_agent
        FROM requests r JOIN request_signatures s USING (request_id)
        """
    ).fetchall()
    out: list[tuple[str, str | None, str | None, str | None, str | None]] = []
    counts: dict[str, int] = {}
    for (rid, ts, method, authority, path, query, ua, accept, lang, ref, ch, sfs, sfm, sfd, sig, sig_in, sig_agent) in rows:
        headers = {
            k: v
            for k, v in {
                "user-agent": ua, "accept": accept, "accept-language": lang, "referer": ref, "sec-ch-ua": ch,
                "sec-fetch-site": sfs, "sec-fetch-mode": sfm, "sec-fetch-dest": sfd,
                "signature-agent": sig_agent, "signature": sig, "signature-input": sig_in,
            }.items()
            if v is not None
        }  # fmt: skip
        auth = authority or ""
        ctx = RequestContext(method or "GET", auth, path or "/", query or "", default_scheme(auth), headers)
        res = verify_request(ctx, sig, sig_in, sig_agent, ts=ts, keys=resolver, clock_skew_s=skew)
        counts[str(res.status)] = counts.get(str(res.status), 0) + 1
        op = agent = cls = None
        if res.status == VALID:
            mapped = reg.operator_for_origin(res.operator_origin)
            op_key, op = mapped if mapped else (None, res.operator_origin or "unknown")
            token = reg.match(ua)
            entry = token if token and (op_key is None or token.operator_key == op_key) else None
            entry = entry or (reg.default_agent_for(op_key) if op_key else None)
            agent = entry.agent_name if entry else "unknown"
            cls = entry.agent_class if entry else CLASS_BROWSING
        out.append((rid, res.status, op, agent, cls))
    s = pa.string()
    _register(con, "_verify", dict.fromkeys(("request_id", "vstatus", "op", "agent", "cls"), s), out)
    return counts


def _features(con: duckdb.DuckDBPyConnection, attach_s: int) -> None:
    """Build `_run_feat`: one row per client run among requests that are neither verified, internal nor declared."""
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE _cand AS
        SELECT r.request_id, r.ts, COALESCE(r.ip_hash, '') AS ip_hash, COALESCE(r.ua_hash, '') AS ua_hash,
               r.cookie_sid_hash AS cookie, r.page_type, r.method, r.user_agent, r.accept, r.sec_ch_ua,
               r.sec_fetch_mode, r.referer, v.vstatus
        FROM requests r
        LEFT JOIN _verify v USING (request_id)
        WHERE COALESCE(v.vstatus, '') <> 'valid'
          AND NOT EXISTS (SELECT 1 FROM _ua_map m WHERE m.ua_hash = r.ua_hash)
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _runs AS
        WITH k AS ({keyed_sql("_cand", attach_s)}), g AS (
          SELECT *, lag(ts) OVER (PARTITION BY ckey ORDER BY ts) AS prev_t FROM k
        )
        SELECT request_id, ts, page_type, method, user_agent, accept, sec_ch_ua, sec_fetch_mode, referer, vstatus,
               hash(ckey, sum(CASE WHEN prev_t IS NULL OR ts - prev_t > INTERVAL {RUN_GAP_MIN} MINUTE THEN 1 ELSE 0 END)
                            OVER (PARTITION BY ckey ORDER BY ts ROWS UNBOUNDED PRECEDING)) AS run
        FROM g
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE _gaps AS
        SELECT run, avg(gap) AS mean_gap, stddev_pop(gap) AS sd_gap, count(gap) AS n_gaps
        FROM (
          SELECT run, epoch(ts - lag(ts) OVER (PARTITION BY run ORDER BY ts)) AS gap
          FROM _runs WHERE page_type NOT IN ('asset', 'beacon')
        ) GROUP BY run
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _run_feat AS
        SELECT a.run, a.n_html, a.n_assets, a.n_beacons, a.n_pagelike, a.ua_browser, a.ua_modern, a.headless,
               a.html_no_sec_fetch, a.html_atypical_accept, a.dur_s, a.invalid_sig, a.first_page,
               epoch(a.first_cart_ts - a.start_ts) AS cart_after_s,
               CASE WHEN g.mean_gap > 0 THEN g.sd_gap / g.mean_gap END AS gap_cv, COALESCE(g.n_gaps, 0) AS n_gaps
        FROM (
          SELECT run,
            count(*) FILTER (WHERE page_type IN ({_HTML_SQL})) AS n_html,
            count(*) FILTER (WHERE page_type = 'asset') AS n_assets,
            count(*) FILTER (WHERE page_type = 'beacon') AS n_beacons,
            count(*) FILTER (WHERE page_type NOT IN ('asset', 'beacon')) AS n_pagelike,
            COALESCE(bool_or(regexp_matches(user_agent, '^Mozilla/5\\.0')
                             AND regexp_matches(user_agent, 'Chrome|Safari|Firefox|Edg')), false) AS ua_browser,
            COALESCE(bool_or(TRY_CAST(regexp_extract(user_agent, 'Chrome/(\\d+)', 1) AS INTEGER) >= 80
                             OR TRY_CAST(regexp_extract(user_agent, 'Firefox/(\\d+)', 1) AS INTEGER) >= 90), false) AS ua_modern,
            COALESCE(bool_or(regexp_matches(COALESCE(user_agent, '') || ' ' || COALESCE(sec_ch_ua, ''),
                             '(?i){HEADLESS_SQL}')), false) AS headless,
            count(*) FILTER (WHERE page_type IN ({_HTML_SQL}) AND sec_fetch_mode IS NULL) AS html_no_sec_fetch,
            count(*) FILTER (WHERE page_type IN ({_HTML_SQL}) AND COALESCE(accept, '') NOT ILIKE '%text/html%')
              AS html_atypical_accept,
            epoch(max(ts) - min(ts)) AS dur_s,
            COALESCE(bool_or(vstatus IN ({_FORGERY_SQL})), false) AS invalid_sig,
            arg_min(page_type, ts) FILTER (WHERE page_type NOT IN ('asset', 'beacon')) AS first_page,
            min(ts) FILTER (WHERE method = 'POST' AND page_type = 'cart_api') AS first_cart_ts,
            min(ts) AS start_ts
          FROM _runs GROUP BY run
        ) a LEFT JOIN _gaps g USING (run)
        """
    )


def _score_runs(con: duckdb.DuckDBPyConnection, cfg: SuspicionConfig) -> int:
    rows = con.execute(
        """
        SELECT run, n_html, n_assets, n_beacons, n_pagelike, ua_browser, ua_modern, headless, html_no_sec_fetch,
               html_atypical_accept, dur_s, invalid_sig, first_page, cart_after_s, gap_cv, n_gaps FROM _run_feat
        """
    ).fetchall()
    out = []
    for (run, n_html, n_assets, n_beacons, n_pagelike, ua_browser, ua_modern, headless, nosf, atyp, dur_s,
         invalid, first_page, cart_after, gap_cv, n_gaps) in rows:  # fmt: skip
        f = RunFeatures(
            n_html=n_html, n_assets=n_assets, n_beacons=n_beacons, n_pagelike=n_pagelike, ua_browser=ua_browser,
            ua_modern=ua_modern, headless_hint=headless, html_missing_sec_fetch=nosf, gap_cv=gap_cv, n_gaps=n_gaps,
            pages_per_min=n_pagelike / max((dur_s or 0) / 60.0, 0.25),
            deep_link_cart_rush=bool(first_page in ("pdp", "cart_api", "checkout") and cart_after is not None and cart_after <= 30),
            atypical_accept_frac=(atyp / n_html) if n_html else 0.0, invalid_signature=invalid,
        )  # fmt: skip
        fired = score_signals(f, cfg)
        score = min(100.0, float(sum(fired.values())))
        out.append((run, score, CLASS_BROWSING if n_beacons > 0 else "user_fetcher"))
    _register(con, "_run_score", {"run": pa.uint64(), "score": pa.float64(), "cls": pa.string()}, out)
    return len(out)


def identify(con: duckdb.DuckDBPyConnection, ctx: Any = None) -> dict[str, int]:
    """Recompute identity for every request. Idempotent; the caller owns the transaction."""
    cfg = settings.load_yaml("identification")
    reg = UARegistry.from_config()
    scfg = SuspicionConfig.from_config(cfg)
    attach_s = int(cfg.get("sessions", {}).get("cookie_attach_s", 120))

    n_ua = _ua_map(con, reg)
    _ip_ok(con, reg)
    sig_counts = _verify_signed(con, reg, cfg)
    _features(con, attach_s)
    n_runs = _score_runs(con, scfg)

    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _ident AS
        SELECT r.request_id,
          CASE WHEN v.vstatus = 'valid' THEN '{TIER_VERIFIED}'
               WHEN u.tier = '{TIER_INTERNAL}' THEN '{TIER_INTERNAL}'
               WHEN u.ua_hash IS NOT NULL THEN '{TIER_DECLARED}'
               WHEN s.score >= {scfg.threshold} THEN '{TIER_SUSPECTED}'
               ELSE '{TIER_HUMAN}' END AS tier,
          CASE WHEN v.vstatus = 'valid' THEN v.op WHEN u.ua_hash IS NOT NULL THEN u.operator
               WHEN s.score >= {scfg.threshold} THEN 'unknown' END AS operator,
          CASE WHEN v.vstatus = 'valid' THEN v.agent WHEN u.ua_hash IS NOT NULL THEN u.agent_name
               WHEN s.score >= {scfg.threshold} THEN 'unknown' END AS agent_name,
          CASE WHEN v.vstatus = 'valid' THEN v.cls WHEN u.ua_hash IS NOT NULL THEN u.agent_class
               WHEN s.score >= {scfg.threshold} THEN s.cls ELSE 'human' END AS agent_class,
          CASE WHEN v.vstatus = 'valid' THEN 1.0
               WHEN u.tier = '{TIER_INTERNAL}' THEN 1.0
               WHEN u.ua_hash IS NOT NULL THEN CASE WHEN i.ua_hash IS NOT NULL THEN {declared_confidence(True)}
                                                    ELSE {declared_confidence(False)} END
               WHEN s.score >= {scfg.threshold} THEN s.score / 100.0
               ELSE 1.0 - COALESCE(s.score, 0) / 100.0 END AS conf,
          v.vstatus AS sig_status,
          CASE WHEN v.vstatus = 'valid' THEN 0.0
               WHEN u.ua_hash IS NOT NULL THEN CASE WHEN v.vstatus IN ({_FORGERY_SQL}) THEN {scfg.weights['invalid_signature']}
                                                    ELSE 0.0 END
               ELSE COALESCE(s.score, 0) END AS suspicion
        FROM requests r
        LEFT JOIN _verify v ON v.request_id = r.request_id
        LEFT JOIN _ua_map u ON u.ua_hash = r.ua_hash
        LEFT JOIN _ip_ok i ON i.ua_hash = r.ua_hash AND i.ip_prefix = r.ip_prefix
        LEFT JOIN _runs rr ON rr.request_id = r.request_id
        LEFT JOIN _run_score s ON s.run = rr.run
        """
    )
    con.execute(
        """
        UPDATE requests SET identity_tier = i.tier, operator = i.operator, agent_name = i.agent_name,
          agent_class = i.agent_class, identity_confidence = i.conf, signature_status = i.sig_status,
          suspicion_score = i.suspicion
        FROM _ident i WHERE requests.request_id = i.request_id
        """
    )
    tiers = dict(con.execute("SELECT identity_tier, count(*) FROM requests GROUP BY 1").fetchall())
    return {
        "ua_tokens_matched": n_ua, "runs_scored": n_runs, "signed_requests": sum(sig_counts.values()),
        **{f"sig_{k}": v for k, v in sig_counts.items()}, **{f"requests_{k}": v for k, v in tiers.items() if k},
    }  # fmt: skip


__all__ = ["identify"]
