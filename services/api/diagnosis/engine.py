"""C7 diagnosis engine: run the blocker rules over agent sessions and pick one terminal blocker per failed session.

Scope: sessions with identity tier verified/declared/suspected that did not convert. Crawlers get only the
infrastructure rules (B01, B12, B13, B16). Each rule emits *unresolved* failures with evidence; the terminal blocker is
the unresolved hit at the deepest funnel stage, then the latest in time, then the most confident (and >= the minimum
terminal confidence). Shopping sessions with no terminal blocker that still ended on an error or stalled mid-funnel are
B99 (unknown) candidates for the optional LLM classifier.

Everything is set-based DuckDB SQL except the capped LLM loop. Idempotent: blocker_hits and the sessions' diagnosis
columns are recomputed from scratch. Never reads synthetic ground truth.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import duckdb

from .. import settings
from ..funnel import load_stage_rules, stage_case_sql
from ..pipeline import RunContext, register_step
from . import rules as rules_mod
from .llm import Cache, SessionSummary, classify_cached, estimate_tokens, get_provider, redact_path
from .sitechecks import USABLE, run_site_checks

DEFAULT_CATALOG = settings.REPO_ROOT / "apps" / "store" / "data" / "catalog.json"
HIT_COLS = "session_id, blocker_id, stage_id, confidence, evidence_ts, ev_ids, site_ev, note"
PAGE_STAGE = {"robots": "S1", "policy": "S1", "home": "S1", "plp": "S1", "search": "S1", "size_guide": "S3",
              "cart": "S5", "login": "S5", "otp_api": "S5", "cart_api": "S5", "checkout": "S6",
              "checkout_api": "S7", "order_confirm": "S8"}  # fmt: skip


def load_config() -> dict[str, Any]:
    cfg = settings.load_yaml("diagnosis")
    cfg.setdefault("scope", {})
    cfg.setdefault("thresholds", {})
    cfg["thresholds"].setdefault("slow_ms", 5000)
    cfg["thresholds"].setdefault("min_terminal_confidence", 0.5)
    cfg["thresholds"].setdefault("min_hit_confidence", 0.3)
    cfg["thresholds"].setdefault("llm_min_confidence", 0.6)
    cfg.setdefault("site_checks", {})
    cfg.setdefault("llm", {})
    return cfg


def _in_list(values: list[str]) -> str:
    return ", ".join("'" + v.replace("'", "''") + "'" for v in values) or "''"


def load_catalog(path: str | Path | None) -> list[dict[str, Any]]:
    p = Path(path) if path else DEFAULT_CATALOG
    if not p.exists():
        return []
    doc = json.loads(p.read_text(encoding="utf-8"))
    return list(doc["products"] if isinstance(doc, dict) else doc)


def _build_catalog(con: duckdb.DuckDBPyConnection, products: list[dict[str, Any]]) -> None:
    con.execute("CREATE OR REPLACE TEMP TABLE _dcat (product_id VARCHAR, size VARCHAR, colour VARCHAR, stock INTEGER, price DOUBLE)")
    rows = [
        (p["id"], str(v.get("size", "")).lower(), str(v.get("colour", "")).lower(), int(v.get("stock", 0)), float(p["price"]))
        for p in products
        for v in p.get("variants", [])
    ]
    if rows:
        con.executemany("INSERT INTO _dcat VALUES (?, ?, ?, ?, ?)", rows)


def _build_tables(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> None:
    scope = cfg["scope"]
    tiers = _in_list(scope.get("tiers", ["verified", "declared", "suspected"]))
    infra = _in_list(scope.get("infra_only_classes", ["search_crawler", "training_crawler"]))
    excluded = _in_list(scope.get("excluded_classes", ["robots_token_only"]))
    stage_expr = stage_case_sql(load_stage_rules())
    page_stage = " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in PAGE_STAGE.items())

    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _dscope AS
        SELECT session_id, start_ts, identity_tier AS tier, agent_class, agent_name, COALESCE(has_beacon, false) AS has_beacon,
               COALESCE(agent_class, '') NOT IN ({infra}) AS shop, max_stage
        FROM sessions
        WHERE identity_tier IN ({tiers}) AND NOT COALESCE(converted, false) AND COALESCE(agent_class, '') NOT IN ({excluded})
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _dreq AS
        SELECT r.request_id, r.session_id, r.ts,
               row_number() OVER (PARTITION BY r.session_id ORDER BY r.ts, r.request_id) AS rn,
               row_number() OVER (PARTITION BY r.session_id ORDER BY r.ts DESC, r.request_id DESC) AS rn_desc,
               r.method, r.path, r.query, r.status, r.error_code, r.duration_ms, r.page_type, r.bytes_out,
               r.unit_price, r.product_id,
               COALESCE({stage_expr}, CASE r.page_type {page_stage} ELSE 'S1' END) AS stage_id
        FROM requests r JOIN _dscope s USING (session_id)
        WHERE NOT r.is_asset AND r.event_type = 'request' AND r.page_type NOT IN ('asset', 'beacon')
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE _dsess AS
        SELECT s.session_id, s.start_ts, s.tier, s.agent_class, s.agent_name, s.has_beacon, s.shop, s.max_stage,
               max(r.ts) FILTER (WHERE r.page_type = 'cart_api' AND r.method = 'POST' AND r.status = 201) AS ok_cart_ts,
               max(r.ts) FILTER (WHERE r.page_type = 'checkout_api' AND r.method = 'POST' AND r.status = 201) AS ok_checkout_ts,
               max(r.ts) FILTER (WHERE r.page_type = 'variant_api') AS last_variant_ts,
               bool_or(r.path = '/api/captcha') AS saw_captcha,
               bool_or(r.page_type IN ('login', 'otp_api')) AS saw_login
        FROM _dscope s JOIN _dreq r USING (session_id)
        GROUP BY s.session_id, s.start_ts, s.tier, s.agent_class, s.agent_name, s.has_beacon, s.shop, s.max_stage
        """
    )
    usable = _in_list(list(USABLE))
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _chk AS
        SELECT check_name, result, details_json,
               CASE WHEN row_number() OVER w = 1 THEN TIMESTAMP '1970-01-01' ELSE run_ts END AS valid_from,
               lead(run_ts) OVER w AS valid_to
        FROM site_checks WHERE result IN ({usable})
        WINDOW w AS (PARTITION BY check_name ORDER BY run_ts)
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE _dsite AS
        SELECT s.session_id,
               any_value(c.result) FILTER (WHERE c.check_name = 'pdp_ssr_price') AS pdp_ssr_price,
               any_value(c.result) FILTER (WHERE c.check_name = 'pdp_jsonld_product') AS pdp_jsonld_product,
               any_value(c.result) FILTER (WHERE c.check_name = 'size_guide_table') AS size_guide_table,
               any_value(c.result) FILTER (WHERE c.check_name = 'captcha_presence') AS captcha_presence,
               any_value(c.result) FILTER (WHERE c.check_name = 'robots_txt') AS robots_txt,
               any_value(CAST(json_extract(c.details_json, '$.blocked_agents') AS VARCHAR[]))
                 FILTER (WHERE c.check_name = 'robots_txt' AND c.result IN ('pass', 'fail')) AS robots_blocked
        FROM _dscope s JOIN _chk c ON s.start_ts >= c.valid_from AND (c.valid_to IS NULL OR s.start_ts < c.valid_to)
        GROUP BY s.session_id
        """
    )


def _evidence_sql(src: str) -> str:
    """Turn a hits table (HIT_COLS) into rows with evidence_json: request items then site-check items."""
    return f"""
        WITH u AS (
          SELECT session_id, blocker_id, unnest(ev_ids) AS rid, unnest(generate_series(1, len(ev_ids))) AS pos, note
          FROM {src}
        ), items AS (
          SELECT u.session_id, u.blocker_id,
                 list(to_json({{'type': 'request', 'request_id': r.request_id,
                               'summary': r.method || ' ' || r.path || ' -> ' || COALESCE(CAST(r.status AS VARCHAR), '?')
                                          || COALESCE(' ' || r.error_code, '')
                                          || CASE WHEN r.unit_price IS NOT NULL THEN ' unit_price=' || CAST(r.unit_price AS BIGINT) ELSE '' END
                                          || COALESCE(' (' || CASE WHEN u.pos = 1 THEN u.note END || ')', '')}})::VARCHAR
                      ORDER BY u.pos) AS req_items
          FROM u JOIN _dreq r ON r.request_id = u.rid GROUP BY u.session_id, u.blocker_id
        )
        SELECT h.session_id, h.blocker_id, h.stage_id, h.confidence, h.evidence_ts,
               '[' || array_to_string(list_concat(
                   COALESCE(i.req_items, CAST([] AS VARCHAR[])),
                   list_transform(h.site_ev, lambda x: to_json({{'type': 'site_check', 'check': split_part(x, '=', 1),
                                                           'result': split_part(x, '=', 2)}})::VARCHAR)), ',') || ']' AS evidence_json
        FROM {src} h LEFT JOIN items i USING (session_id, blocker_id)
    """


def run_rules(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any], only: list[str] | None = None) -> int:
    """Fill `_dhits` from the registered rules. Returns the number of raw hits."""
    branches = [
        f"SELECT session_id, blocker_id, stage_id, CAST(confidence AS DOUBLE) AS confidence, evidence_ts, ev_ids, site_ev, note "
        f"FROM ({sql}) AS t(session_id, blocker_id, stage_id, confidence, evidence_ts, ev_ids, site_ev, note)"
        for sql in rules_mod.rule_sql(cfg, only).values()
    ]
    con.execute("CREATE OR REPLACE TEMP TABLE _dhits AS " + " UNION ALL ".join(branches))
    min_hit = float(cfg["thresholds"]["min_hit_confidence"])
    con.execute(f"DELETE FROM _dhits WHERE confidence < {min_hit}")
    return int(con.execute("SELECT count(*) FROM _dhits").fetchone()[0])  # type: ignore[index]


def _select_terminal(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> None:
    min_term = float(cfg["thresholds"]["min_terminal_confidence"])
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _dterm AS
        SELECT session_id, blocker_id, confidence FROM (
          SELECT session_id, blocker_id, confidence,
                 row_number() OVER (PARTITION BY session_id
                                    ORDER BY CAST(substr(stage_id, 2) AS INTEGER) DESC, evidence_ts DESC,
                                             confidence DESC, blocker_id) AS rk
          FROM _dhits WHERE confidence >= {min_term}
        ) WHERE rk = 1
        """
    )


def _write_hits(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("DELETE FROM blocker_hits")
    con.execute(
        f"""
        INSERT INTO blocker_hits
        SELECT e.session_id, e.blocker_id, e.stage_id, e.confidence, (t.blocker_id IS NOT NULL) AS is_terminal, e.evidence_json
        FROM ({_evidence_sql('_dhits')}) e
        LEFT JOIN _dterm t ON t.session_id = e.session_id AND t.blocker_id = e.blocker_id
        """
    )
    con.execute("UPDATE sessions SET terminal_blocker_id = NULL, blocker_confidence = NULL, diagnosis_method = NULL")
    con.execute(
        """
        UPDATE sessions SET terminal_blocker_id = t.blocker_id, blocker_confidence = t.confidence, diagnosis_method = 'rules'
        FROM _dterm t WHERE sessions.session_id = t.session_id
        """
    )


def _b99_candidates(con: duckdb.DuckDBPyConnection) -> int:
    """Shopping sessions with no terminal blocker that ended on an error or stalled mid-funnel."""
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE _dunk AS
        SELECT s.session_id, s.agent_class, s.max_stage, r.request_id AS last_rid, r.ts AS last_ts
        FROM _dsess s JOIN _dreq r ON r.session_id = s.session_id AND r.rn_desc = 1
        WHERE s.shop AND s.session_id NOT IN (SELECT session_id FROM _dterm)
          AND (COALESCE(r.status, 200) >= 400
               OR (s.agent_class = 'browsing_agent' AND COALESCE(CAST(substr(s.max_stage, 2) AS INTEGER), 0) BETWEEN 2 AND 7))
        """
    )
    return int(con.execute("SELECT count(*) FROM _dunk").fetchone()[0])  # type: ignore[index]


def _write_b99(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE _dhits_unk AS
        SELECT session_id, 'B99' AS blocker_id, COALESCE(max_stage, 'S1') AS stage_id, 0.3 AS confidence, last_ts AS evidence_ts,
               [last_rid] AS ev_ids, CAST([] AS VARCHAR[]) AS site_ev, CAST(NULL AS VARCHAR) AS note
        FROM _dunk
        """
    )
    con.execute(
        f"""
        INSERT INTO blocker_hits
        SELECT session_id, blocker_id, stage_id, confidence, true, evidence_json FROM ({_evidence_sql('_dhits_unk')})
        """
    )
    con.execute(
        """
        UPDATE sessions SET terminal_blocker_id = 'B99', blocker_confidence = 0.3, diagnosis_method = 'rules'
        FROM _dunk u WHERE sessions.session_id = u.session_id
        """
    )


def _llm_pass(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any], provider_name: str | None) -> dict[str, Any]:
    out: dict[str, Any] = {"llm_provider": "off", "llm_candidates": 0, "llm_classified": 0, "llm_cached": 0, "llm_est_tokens": 0}
    if (provider_name or os.getenv("AGENTLENS_LLM_PROVIDER") or "mock").lower() in ("off", "none", "rules"):
        return out
    provider = get_provider(provider_name)
    out["llm_provider"] = provider.name
    cap = int(os.getenv("AGENTLENS_LLM_MAX_SESSIONS") or cfg["llm"].get("max_sessions", 200))
    n_req = int(cfg["llm"].get("max_requests", 40))
    cands = con.execute("SELECT session_id, agent_class, max_stage FROM _dunk ORDER BY last_ts DESC, session_id LIMIT ?", [cap]).fetchall()
    out["llm_candidates"] = len(cands)
    if not cands:
        return out
    ids = [c[0] for c in cands]
    rows = con.execute(
        """
        SELECT session_id, method, path, status, error_code, duration_ms, page_type FROM (
          SELECT *, row_number() OVER (PARTITION BY session_id ORDER BY ts DESC, request_id DESC) AS k
          FROM _dreq WHERE session_id IN (SELECT unnest(?))
        ) WHERE k <= ? ORDER BY session_id, rn_desc DESC
        """,
        [ids, n_req],
    ).fetchall()
    by_session: dict[str, list[dict[str, Any]]] = {}
    for sid, method, path, status, code, dur, ptype in rows:
        by_session.setdefault(sid, []).append(
            {"method": method, "path": redact_path(path), "status": status, "error_code": code, "duration_ms": dur, "page_type": ptype}
        )
    cache = Cache()
    min_conf = float(cfg["thresholds"]["llm_min_confidence"])
    prompts: list[str] = []
    assigned: list[tuple[str, str, float, str]] = []
    notes: list[tuple[str, str]] = []
    for sid, agent_class, max_stage in cands:
        summary = SessionSummary(sid, agent_class, max_stage, by_session.get(sid, []))
        verdict, cached = classify_cached(provider, cache, summary)
        out["llm_cached"] += int(cached)
        if not cached and provider.name != "mock":
            prompts.append(summary.prompt())
        if verdict is None:
            continue
        text = verdict.rationale + (f" Suggested new blocker: {verdict.suggested_new_blocker}." if verdict.suggested_new_blocker else "")
        if verdict.blocker_id != "B99" and verdict.confidence >= min_conf:
            assigned.append((sid, verdict.blocker_id, verdict.confidence, text))
        else:
            notes.append((sid, text))
    out["llm_est_tokens"] = estimate_tokens(prompts)
    out["llm_classified"] = len(assigned)
    for sid, bid, conf, text in assigned:
        con.execute("DELETE FROM blocker_hits WHERE session_id = ? AND blocker_id = 'B99'", [sid])
        last = con.execute("SELECT request_id, method, path, status, error_code FROM _dreq WHERE session_id = ? AND rn_desc = 1", [sid]).fetchone()
        assert last is not None
        ev = [{"type": "request", "request_id": last[0], "summary": f"{last[1]} {last[2]} -> {last[3]}" + (f" {last[4]}" if last[4] else "")},
              {"type": "llm_note", "summary": text}]  # fmt: skip
        stage = con.execute("SELECT COALESCE(max_stage, 'S1') FROM _dsess WHERE session_id = ?", [sid]).fetchone()[0]  # type: ignore[index]
        con.execute("INSERT INTO blocker_hits VALUES (?, ?, ?, ?, true, ?)", [sid, bid, stage, conf, json.dumps(ev)])
        con.execute(
            "UPDATE sessions SET terminal_blocker_id = ?, blocker_confidence = ?, diagnosis_method = 'llm' WHERE session_id = ?",
            [bid, conf, sid],
        )
    for sid, text in notes:
        row = con.execute("SELECT evidence_json FROM blocker_hits WHERE session_id = ? AND blocker_id = 'B99'", [sid]).fetchone()
        if row:
            ev = json.loads(row[0])
            ev.append({"type": "llm_note", "summary": text})
            con.execute("UPDATE blocker_hits SET evidence_json = ? WHERE session_id = ? AND blocker_id = 'B99'", [json.dumps(ev), sid])
    return out


def diagnose(con: duckdb.DuckDBPyConnection, ctx: RunContext | None = None) -> dict[str, Any]:
    params = ctx.params if ctx else {}
    cfg = load_config()
    sc = cfg["site_checks"]

    base_url = params.get("site_url") or os.getenv("AGENTLENS_SITE_URL") or sc.get("base_url") or ""
    probe: dict[str, Any] = {"status": "not_run"}
    products = load_catalog(params.get("catalog_path") or os.getenv("AGENTLENS_CATALOG") or sc.get("catalog_path") or None)
    if not params.get("skip_site_probe"):
        probe = run_site_checks(
            con, base_url, transport=params.get("site_transport"), timeout_s=float(sc.get("timeout_s", 5)),
            pdp_sample=int(sc.get("pdp_sample", 5)), catalog_slugs=[str(p["slug"]) for p in products if "slug" in p],
        )  # fmt: skip

    _build_catalog(con, products)
    _build_tables(con, cfg)
    n_scope = int(con.execute("SELECT count(*) FROM _dsess").fetchone()[0])  # type: ignore[index]
    n_raw = run_rules(con, cfg)
    _select_terminal(con, cfg)
    _write_hits(con)
    n_unk = _b99_candidates(con)
    _write_b99(con)
    llm = _llm_pass(con, cfg, params.get("llm_provider"))

    terminal = con.execute(
        "SELECT terminal_blocker_id, count(*) FROM sessions WHERE terminal_blocker_id IS NOT NULL GROUP BY 1 ORDER BY 1"
    ).fetchall()
    counts: dict[str, Any] = {
        "sessions_in_scope": n_scope, "hits": n_raw, "b99_candidates": n_unk,
        "terminal_sessions": sum(int(n) for _, n in terminal), "site_probe": probe["status"],
        "catalog_products": len(products),
    }  # fmt: skip
    counts.update(llm)
    counts.update({f"terminal_{b}": int(n) for b, n in terminal})
    return counts


def _step(con: duckdb.DuckDBPyConnection, ctx: RunContext) -> dict[str, Any]:
    return diagnose(con, ctx)


register_step("diagnose", _step, replace=True)
