"""Health, meta, overview, funnel, compare and site checks."""

from __future__ import annotations

import json
import math
import os
from datetime import UTC, date, datetime, timedelta
from typing import Any

import duckdb
from fastapi import APIRouter, Depends, Query

from .. import __version__, settings
from . import analytics as an
from . import recs, runs
from .deps import (
    AGENT_CLASSES,
    DB,
    SEGMENTS,
    Filters,
    data_bounds,
    filters_dep,
    get_read,
    iso,
    parse_filters,
    resolve_window,
    validation_error,
)

router = APIRouter()

ZERO_RISK = {"low": 0, "base": 0, "high": 0}


@router.get("/health")
def health() -> dict[str, Any]:
    state = "missing"
    try:
        if DB.exists():
            with DB.read() as cur:
                cur.execute("SELECT 1").fetchall()
            state = "ok"
    except Exception:
        state = "error"
    return {
        "status": "ok" if state == "ok" else "degraded", "version": __version__,
        "time": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "db": state, "demo_mode": settings.demo_mode(),
    }  # fmt: skip


@router.get("/meta")
def meta(cur: duckdb.DuckDBPyConnection = Depends(get_read)) -> dict[str, Any]:
    ctx = an.load_ctx()
    ops = cur.execute(
        f"SELECT DISTINCT operator FROM sessions WHERE {ctx.agent_sql()} AND operator IS NOT NULL ORDER BY operator"
    ).fetchall()
    bounds = data_bounds(cur)
    return {
        "version": __version__, "demo_mode": settings.demo_mode(), "store_name": os.getenv("AGENTLENS_STORE_NAME", "AgentLens Demo Store"),
        "currency": "INR", "operators": [r[0] for r in ops], "agent_classes": list(AGENT_CLASSES), "segments": list(SEGMENTS),
        "date_bounds": {"min": bounds[0], "max": bounds[1]} if bounds else None,
        "default_window": {"from": bounds[0], "to": bounds[1]} if bounds else None, "last_run": runs.last_run(cur),
    }  # fmt: skip


# ---------------------------------------------------------------- overview
def kpis_for(cur: duckdb.DuckDBPyConnection, ctx: an.Ctx, f: Filters, w: Any) -> tuple[dict[str, Any], an.ImpactResult]:
    empty: dict[str, Any] = {"sessions": 0, "converted": 0, "revenue": 0.0, "pages": 0, "failed": 0, "diagnosed": 0,
                             "tiers": {"verified": 0, "declared": 0, "suspected": 0}}  # fmt: skip
    agent = empty if f.segment == "humans" else an.totals(cur, ctx, f, w)
    everyone = an.totals(cur, ctx, f, w, segment="all_agents", filters=False)
    human = an.totals(cur, ctx, f, w, segment="humans")
    res = an.compute_impact(cur, ctx, f, w)
    total = human["sessions"] + everyone["sessions"]
    risk = res.risk_total()
    monthly_revenue = agent["revenue"] * res.k
    n = agent["sessions"]
    kp = {
        "agent_sessions": n, "total_sessions": total, "agent_share": n / total if total else 0.0,
        "agent_converted": agent["converted"], "agent_conversion": agent["converted"] / n if n else 0.0,
        "human_sessions": human["sessions"], "human_conversion": human["converted"] / human["sessions"] if human["sessions"] else 0.0,
        "agent_revenue_inr": round(agent["revenue"], 2), "risk_inr": risk,
        "risk_pct_of_agent_revenue": risk["base"] / monthly_revenue if monthly_revenue else 0.0,
        "identity_coverage": (agent["tiers"]["verified"] + agent["tiers"]["declared"]) / n if n else 0.0,
        "verified_share": agent["tiers"]["verified"] / n if n else 0.0, "diagnosis_coverage": res.coverage,
    }  # fmt: skip
    return kp, res


def deltas(now: dict[str, Any], before: dict[str, Any] | None) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for key, a in now.items():
        if before is None:
            out[key] = None
            continue
        b = before[key]
        if key == "risk_inr":
            a, b = a["base"], b["base"]
        out[key] = (a / b - 1) if b else None
    return out


@router.get("/overview")
def overview(f: Filters = Depends(filters_dep), cur: duckdb.DuckDBPyConnection = Depends(get_read)) -> dict[str, Any]:
    ctx = an.load_ctx()
    w = resolve_window(cur, f.from_, f.to)
    kp, res = kpis_for(cur, ctx, f, w)
    bounds = data_bounds(cur)
    prev = w.previous()
    before = None
    if bounds and prev.from_ >= bounds[0]:
        before_kp, _ = kpis_for(cur, ctx, f, prev)
        before = before_kp if (before_kp["agent_sessions"] or before_kp["human_sessions"]) else None

    mix_where, mix_params = an.population(ctx, f, w)
    ops = cur.execute(
        f"""SELECT COALESCE(operator, 'unknown'), count(*), count(*) FILTER (WHERE identity_tier = 'verified'),
                   count(*) FILTER (WHERE identity_tier = 'declared'), count(*) FILTER (WHERE identity_tier = 'suspected')
            FROM sessions WHERE {mix_where} GROUP BY 1 ORDER BY 2 DESC, 1""",
        mix_params,
    ).fetchall()
    classes = cur.execute(
        f"SELECT agent_class, count(*) FROM sessions WHERE {mix_where} AND agent_class IS NOT NULL GROUP BY 1 ORDER BY 2 DESC, 1",
        mix_params,
    ).fetchall()
    n = kp["agent_sessions"] or 1
    stored = recs.stored_recs(cur)
    top = recs.recommendations(ctx, res, stored)[:3]
    return {
        "window": w.as_dict(), "kpis": kp, "kpi_deltas": deltas(kp, before), "timeseries": an.timeseries(cur, ctx, f, w),
        "annotations": recs.annotations_between(cur, w.from_, w.to),
        "operator_mix": [
            {"operator": o, "sessions": c, "share": c / n,
             "tier_mix": {"verified": v / c, "declared": d / c, "suspected": s / c}}
            for o, c, v, d, s in ops
        ],
        "class_mix": [{"agent_class": k, "sessions": c, "share": c / n} for k, c in classes],
        "top_fixes": [
            {k: r[k] for k in ("rec_id", "blocker_id", "blocker_name", "title", "risk_inr_base", "effort", "priority_score", "owner", "status")}
            for r in top
        ],
    }  # fmt: skip


# ---------------------------------------------------------------- funnel
def stage_blockers(res: an.ImpactResult) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {sid: [] for sid in an.STAGE_IDS}
    for i in res.items:
        out[i.stage].append({"blocker_id": i.blocker_id, "name": i.name, "sessions_blocked": i.sessions_blocked,
                             "share_of_failed": i.share_of_failed, "risk_inr_base": i.base})  # fmt: skip
    for lst in out.values():
        lst.sort(key=lambda b: -b["sessions_blocked"])
    return out


@router.get("/funnel")
def funnel(
    compare: str | None = Query(None), f: Filters = Depends(filters_dep), cur: duckdb.DuckDBPyConnection = Depends(get_read),
) -> dict[str, Any]:  # fmt: skip
    if compare is not None and compare not in SEGMENTS:
        raise validation_error("Invalid compare segment", {"compare": f"must be one of {', '.join(SEGMENTS)}"})
    ctx = an.load_ctx()
    w = resolve_window(cur, f.from_, f.to)
    stages = an.stage_defs()
    names = {s["id"]: s["name"] for s in stages}
    primary = an.funnel_series(f.segment, an.reach(cur, ctx, f, w, f.segment), names)
    cmp_seg = compare or "humans"
    cmp_series = an.funnel_series(cmp_seg, an.reach(cur, ctx, f, w, cmp_seg), names)
    res = an.compute_impact(cur, ctx, f, w)
    return {"window": w.as_dict(), "stages": stages, "primary": primary, "compare": cmp_series, "stage_blockers": stage_blockers(res)}


# ---------------------------------------------------------------- compare
def normal_cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def two_proportion_z(x1: int, n1: int, x2: int, n2: int, min_sessions: int, alpha: float = 0.05) -> dict[str, Any]:
    base: dict[str, Any] = {"test": "two_proportion_z", "min_sessions": min_sessions}
    if n1 < min_sessions or n2 < min_sessions:
        return {**base, "enough_data": False, "z": None, "p_value": None, "significant": False,
                "note": f"Not enough data: each window needs at least {min_sessions} sessions (have {n1} and {n2})."}  # fmt: skip
    p1, p2, pooled = x1 / n1, x2 / n2, (x1 + x2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        return {**base, "enough_data": True, "z": 0.0, "p_value": 1.0, "significant": False,
                "note": "No variation in conversion across both windows, so the test is not informative."}  # fmt: skip
    z = (p2 - p1) / se
    p = min(1.0, 2 * (1 - normal_cdf(abs(z))))
    sig = p < alpha
    note = (
        f"The change in conversion is statistically significant (two-proportion z-test, p {'< 0.001' if p < 0.001 else f'= {p:.3f}'})."
        if sig else f"The change is not statistically significant at the {round(alpha * 100)}% level (p = {p:.3f}). It could be noise."
    )
    return {**base, "enough_data": True, "z": round(z, 3), "p_value": float(f"{p:.3g}"), "significant": sig, "note": note}


def suggested_windows(cur: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    bounds = data_bounds(cur)
    if not bounds:
        return []
    lo, hi = date.fromisoformat(bounds[0]), date.fromisoformat(bounds[1])
    out = []
    for a in recs.annotations_between(cur, "0001-01-01", "9999-12-31"):
        if a["type"] == "note":
            continue
        day = date.fromisoformat(a["ts"][:10])
        span = min(7, (day - timedelta(days=1) - lo).days + 1, (hi - day).days + 1)
        if span >= 1:
            out.append({
                "label": f'Around "{a["label"]}"', "annotation_id": a["annotation_id"],
                "a": {"from": (day - timedelta(days=span)).isoformat(), "to": (day - timedelta(days=1)).isoformat()},
                "b": {"from": day.isoformat(), "to": (day + timedelta(days=span - 1)).isoformat()},
            })  # fmt: skip
    return out


@router.get("/compare")
def compare(
    a_from: str | None = None, a_to: str | None = None, b_from: str | None = None, b_to: str | None = None,
    segment: str | None = None, operator: str | None = None, agent_class: str | None = None,
    cur: duckdb.DuckDBPyConnection = Depends(get_read),
) -> dict[str, Any]:  # fmt: skip
    given = {"a_from": a_from, "a_to": a_to, "b_from": b_from, "b_to": b_to}
    missing = {k: "required" for k, v in given.items() if not v}
    if missing:
        raise validation_error("Missing window parameters", missing)
    for k, v in given.items():
        try:
            date.fromisoformat(str(v))
        except ValueError:
            missing[k] = "must be a YYYY-MM-DD date"
    if missing:
        raise validation_error("Invalid window parameters", missing)
    f = parse_filters(None, None, segment, operator, agent_class)
    ctx = an.load_ctx()
    stages = an.stage_defs()
    names = {s["id"]: s["name"] for s in stages}

    def summarize(frm: str, to: str) -> dict[str, Any]:
        w = resolve_window(cur, frm, to)
        if f.segment == "humans":
            h = an.totals(cur, ctx, f, w, segment="humans")
            return {"window": w.as_dict(), "sessions": h["sessions"], "converted": h["converted"],
                    "conversion": h["converted"] / h["sessions"] if h["sessions"] else 0.0, "agent_revenue_inr": 0,
                    "risk_inr": dict(ZERO_RISK), "funnel": an.funnel_series("humans", an.reach(cur, ctx, f, w, "humans"), names),
                    "blocker_shares": []}  # fmt: skip
        t = an.totals(cur, ctx, f, w)
        res = an.compute_impact(cur, ctx, f, w)
        return {
            "window": w.as_dict(), "sessions": t["sessions"], "converted": t["converted"],
            "conversion": t["converted"] / t["sessions"] if t["sessions"] else 0.0, "agent_revenue_inr": round(t["revenue"], 2),
            "risk_inr": res.risk_total(), "funnel": an.funnel_series(f.segment, an.reach(cur, ctx, f, w, f.segment), names),
            "blocker_shares": [{"blocker_id": i.blocker_id, "name": i.name, "sessions_blocked": i.sessions_blocked,
                                "share_of_failed": i.share_of_failed, "risk_base_inr": i.base} for i in res.items],
        }  # fmt: skip

    a = summarize(str(a_from), str(a_to))
    b = summarize(str(b_from), str(b_to))
    return {
        "segment": f.segment, "a": a, "b": b,
        "delta": {
            "sessions": b["sessions"] - a["sessions"], "conversion_pp": (b["conversion"] - a["conversion"]) * 100,
            "conversion_relative": b["conversion"] / a["conversion"] - 1 if a["conversion"] else None,
            "agent_revenue_inr": b["agent_revenue_inr"] - a["agent_revenue_inr"],
            "risk_base_inr": b["risk_inr"]["base"] - a["risk_inr"]["base"],
        },
        "significance": two_proportion_z(a["converted"], a["sessions"], b["converted"], b["sessions"], ctx.min_sessions),
        "suggested_windows": suggested_windows(cur),
    }  # fmt: skip


# ---------------------------------------------------------------- site checks
def site_checks_latest(cur: duckdb.DuckDBPyConnection, as_of: str | None = None) -> list[dict[str, Any]]:
    """Latest result per check (real probes only: skipped runs and the probe marker are not checks)."""
    where, params = "result <> 'skipped' AND check_name <> 'site_probe'", []
    if as_of:
        where += " AND CAST(run_ts AS DATE) <= ?"
        params.append(as_of)
    rows = cur.execute(
        f"""SELECT check_id, run_ts, check_name, target, result, details_json FROM site_checks WHERE {where}
            QUALIFY row_number() OVER (PARTITION BY check_name ORDER BY run_ts DESC, check_id) = 1 ORDER BY check_name""",
        params,
    ).fetchall()
    out = []
    for cid, ts, name, target, result, details in rows:
        try:
            doc = json.loads(details) if details else {}
        except ValueError:
            doc = {}
        out.append({"check_id": cid, "run_ts": iso(ts), "check_name": name, "target": target or "",
                    "result": result if result in ("pass", "fail", "warn") else "warn",
                    "details": doc if isinstance(doc, dict) else {"value": doc}})  # fmt: skip
    return out


@router.get("/site-checks")
def site_checks(to: str | None = None, cur: duckdb.DuckDBPyConnection = Depends(get_read)) -> dict[str, Any]:
    f = parse_filters(None, to)
    return {"items": site_checks_latest(cur, f.to)}
