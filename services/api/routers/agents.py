"""GET /agents and GET /agents/{operator}/{agent_name}."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import duckdb
from fastapi import APIRouter, Depends

from . import analytics as an
from .deps import Filters, Window, filters_dep, get_read, iso, not_found, resolve_window, slug

router = APIRouter()

SIG_RANK = ("valid", "invalid_sig", "expired", "unknown_key", "fetch_failed")
SIG_CASE = "CASE signature_status " + " ".join(f"WHEN '{s}' THEN {i}" for i, s in enumerate(SIG_RANK)) + " ELSE 5 END"


def _agent_key(op: str | None, name: str | None) -> tuple[str, str]:
    return op or "unknown", name or "unknown"


def agent_rows(cur: duckdb.DuckDBPyConnection, ctx: an.Ctx, f: Filters, w: Window) -> list[dict[str, Any]]:
    if f.segment == "humans":
        return []
    where, params = an.population(ctx, f, w)
    groups = cur.execute(
        f"""SELECT operator, agent_name, agent_class, count(*), count(*) FILTER (WHERE converted), COALESCE(sum(page_count), 0),
                   count(*) FILTER (WHERE identity_tier = 'verified'), count(*) FILTER (WHERE identity_tier = 'declared'),
                   count(*) FILTER (WHERE identity_tier = 'suspected'), max(start_ts)
            FROM sessions WHERE {where} GROUP BY 1, 2, 3""",
        params,
    ).fetchall()
    if not groups:
        return []
    blockers = cur.execute(
        f"""SELECT operator, agent_name, terminal_blocker_id, count(*) FROM sessions
            WHERE {where} AND NOT converted AND terminal_blocker_id IS NOT NULL GROUP BY 1, 2, 3""",
        params,
    ).fetchall()
    where_s, params_s = an.population(ctx, f, w, alias="s")
    sigs = cur.execute(
        f"""WITH sig AS (
              SELECT session_id, min({SIG_CASE}) AS rk FROM requests
              WHERE signature_status IS NOT NULL AND session_id IS NOT NULL GROUP BY session_id)
            SELECT s.operator, s.agent_name, COALESCE(sig.rk, 5), count(*)
            FROM sessions s LEFT JOIN sig ON sig.session_id = s.session_id WHERE {where_s} GROUP BY 1, 2, 3""",
        params_s,
    ).fetchall()
    total = sum(int(g[3]) for g in groups)
    by_block: dict[tuple[str, str], list[tuple[str, int]]] = {}
    for op, name, bid, n in blockers:
        by_block.setdefault(_agent_key(op, name), []).append((bid, int(n)))
    by_sig: dict[tuple[str, str], dict[str, int]] = {}
    for op, name, rk, n in sigs:
        counts = by_sig.setdefault(_agent_key(op, name), dict.fromkeys(an.SIGNATURE_STATUSES, 0))
        counts[an.SIGNATURE_STATUSES[int(rk)]] += int(n)
    rows = []
    for op, name, cls, n, conv, pages, v, d, s, last in groups:
        key = _agent_key(op, name)
        n = int(n)
        failed = n - int(conv)
        top = max(by_block.get(key, []), key=lambda b: (b[1], b[0]), default=None)
        rows.append({
            "operator": key[0], "agent_name": key[1], "agent_class": cls, "sessions": n,
            "share_of_agent_sessions": n / total if total else 0.0, "pages_per_session": int(pages) / n if n else 0.0,
            "conversion": int(conv) / n if n else 0.0,
            "tier_mix": {"verified": v / n, "declared": d / n, "suspected": s / n},
            "top_blocker": {"blocker_id": top[0], "name": an.blocker_name(ctx, top[0]), "share_of_failed": top[1] / failed}
            if top and failed else None,
            "signature_status_counts": by_sig.get(key, dict.fromkeys(an.SIGNATURE_STATUSES, 0)), "last_seen": iso(last),
        })  # fmt: skip
    rows.sort(key=lambda r: (-r["sessions"], r["operator"], r["agent_name"]))
    return rows


def crawler_rows(cur: duckdb.DuckDBPyConnection, f: Filters, w: Window) -> list[dict[str, Any]]:
    if f.segment != "all_agents" or (f.agent_class and f.agent_class not in an.CRAWLER_CLASSES):
        return []
    classes = ", ".join(f"'{c}'" for c in an.CRAWLER_CLASSES)
    conds, params = [f"agent_class IN ({classes})", "CAST(start_ts AS DATE) BETWEEN ? AND ?"], [w.from_, w.to]
    if f.operator:
        conds.append("operator = ?")
        params.append(f.operator)
    if f.agent_class:
        conds.append("agent_class = ?")
        params.append(f.agent_class)
    rows = cur.execute(
        f"""SELECT operator, agent_name, agent_class, sum(request_count), sum(page_count), max(start_ts)
            FROM sessions WHERE {' AND '.join(conds)} GROUP BY 1, 2, 3 ORDER BY 4 DESC""",
        params,
    ).fetchall()
    robots = {
        _agent_key(r[0], r[1])
        for r in cur.execute(
            f"""SELECT DISTINCT operator, agent_name FROM requests
                WHERE page_type = 'robots' AND agent_class IN ({classes}) AND CAST(ts AS DATE) BETWEEN ? AND ?""",
            [w.from_, w.to],
        ).fetchall()
    }
    return [
        {"operator": _agent_key(op, name)[0], "agent_name": _agent_key(op, name)[1], "agent_class": cls, "requests": int(reqs or 0),
         "pages": int(pages or 0), "robots_txt_fetched": _agent_key(op, name) in robots, "last_seen": iso(last)}
        for op, name, cls, reqs, pages, last in rows
    ]  # fmt: skip


@router.get("/agents")
def agents(f: Filters = Depends(filters_dep), cur: duckdb.DuckDBPyConnection = Depends(get_read)) -> dict[str, Any]:
    ctx = an.load_ctx()
    w = resolve_window(cur, f.from_, f.to)
    return {"window": w.as_dict(), "items": agent_rows(cur, ctx, f, w), "crawlers": crawler_rows(cur, f, w)}


@router.get("/agents/{operator}/{agent_name}")
def agent_detail(
    operator: str, agent_name: str, f: Filters = Depends(filters_dep), cur: duckdb.DuckDBPyConnection = Depends(get_read),
) -> dict[str, Any]:  # fmt: skip
    ctx = an.load_ctx()
    known = cur.execute(
        f"SELECT operator, agent_name, any_value(agent_class), any_value(identity_tier) FROM sessions WHERE {ctx.agent_sql()} GROUP BY 1, 2"
    ).fetchall()
    match = next((k for k in known if slug(_agent_key(k[0], k[1])[0]) == slug(operator) and slug(_agent_key(k[0], k[1])[1]) == slug(agent_name)), None)
    if match is None:
        raise not_found(f"Agent {operator}/{agent_name} not found")
    op, name, cls, _tier = match
    w = resolve_window(cur, f.from_, f.to)
    row = next((r for r in agent_rows(cur, ctx, f, w) if (r["operator"], r["agent_name"]) == _agent_key(op, name)), None)
    sig_blank = dict.fromkeys(an.SIGNATURE_STATUSES, 0)
    agent = row or {
        "operator": _agent_key(op, name)[0], "agent_name": _agent_key(op, name)[1], "agent_class": cls, "sessions": 0,
        "share_of_agent_sessions": 0.0, "pages_per_session": 0.0, "conversion": 0.0,
        "tier_mix": {"verified": 0.0, "declared": 0.0, "suspected": 0.0}, "top_blocker": None, "signature_status_counts": sig_blank,
        "last_seen": f"{w.to}T00:00:00Z",
    }  # fmt: skip
    ident = "operator IS NOT DISTINCT FROM ? AND agent_name IS NOT DISTINCT FROM ?"
    key = [op, name]
    ua = an.one_row(cur, f"SELECT user_agent FROM requests WHERE {ident} AND user_agent IS NOT NULL LIMIT 1", key)
    sa = an.one_row(cur, f"SELECT signature_agent FROM requests WHERE {ident} AND signature_agent IS NOT NULL LIMIT 1", key)
    conf = an.one_row(cur, f"SELECT avg(identity_confidence) FROM sessions WHERE {ident}", key)

    base = f"{ident} AND {ctx.agent_sql()} AND CAST(start_ts AS DATE) BETWEEN ? AND ?"
    bp = [*key, w.from_, w.to]
    daily = {
        r[0].isoformat(): r
        for r in cur.execute(
            f"SELECT CAST(start_ts AS DATE), count(*), count(*) FILTER (WHERE converted) FROM sessions WHERE {base} GROUP BY 1", bp
        ).fetchall()
    }
    trend = []
    day = date.fromisoformat(w.from_)
    while day <= date.fromisoformat(w.to):
        r = daily.get(day.isoformat())
        trend.append({"date": day.isoformat(), "sessions": int(r[1]) if r else 0, "conversion": r[2] / r[1] if r and r[1] else 0.0})
        day += timedelta(days=1)
    blk = cur.execute(
        f"SELECT terminal_blocker_id, count(*) FROM sessions WHERE {base} AND NOT converted AND terminal_blocker_id IS NOT NULL "
        "GROUP BY 1 ORDER BY 2 DESC, 1",
        bp,
    ).fetchall()
    failed = sum(int(b[1]) for b in blk)
    recent = cur.execute(
        f"SELECT {an.session_cols()} FROM sessions WHERE {base} ORDER BY start_ts DESC, session_id LIMIT 10", bp
    ).fetchall()
    return {
        "window": w.as_dict(), "agent": agent,
        "identity": {"user_agent_example": ua[0] if ua else None, "signature_agent": sa[0] if sa else None,
                     "ip_match_rate": None, "avg_identity_confidence": float(conf[0]) if conf and conf[0] is not None else 0.0},
        "trend": trend,
        "blockers": [{"blocker_id": b, "name": an.blocker_name(ctx, b), "sessions": int(n), "share_of_failed": int(n) / failed} for b, n in blk],
        "recent_sessions": [an.session_row(ctx, r) for r in recent],
    }  # fmt: skip
