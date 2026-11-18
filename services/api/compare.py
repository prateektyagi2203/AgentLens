"""Before/after comparison of two windows (the Before/After page, `GET /compare`, the report's before/after section).

Everything is computed from `sessions` + `blocker_hits` with the same impact model as the rest of the product
(`routers.analytics`), so the numbers on this page, the funnel and the blockers page always agree. See docs/before-after.md.

Public functions (all take a DuckDB connection, read-only is fine):

* `compare_windows(con, a_from, a_to, b_from, b_to, *, segment="all_agents", operator=None, agent_class=None) -> dict`
  The exact `Compare` shape of docs/api-contract.md 3.8: `{segment, a, b, delta, significance, suggested_windows}`.
* `suggested_windows(con) -> list[dict]`: equal-length windows around every config_change / marked_fixed annotation.
* `before_after(con, *, segment=..., operator=None, agent_class=None, annotation_id=None) -> dict | None`:
  `compare_windows` for the first suggested window (or a chosen annotation) plus headline lift numbers, per-blocker
  deltas and a human control group. `None` when there is no annotation to compare around.
* `two_proportion_z(x1, n1, x2, n2, min_sessions) -> dict`: the significance block.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

import duckdb

from .routers import analytics as an
from .routers import recs
from .routers.deps import Filters, Window, data_bounds, resolve_window

ZERO_RISK = {"low": 0, "base": 0, "high": 0}


def normal_cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def two_proportion_z(x1: int, n1: int, x2: int, n2: int, min_sessions: int, alpha: float = 0.05) -> dict[str, Any]:
    """Two-sided two-proportion z-test (pooled variance) on conversion; `x` = conversions, `n` = sessions."""
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
    ptxt = "< 0.001" if p < 0.001 else f"= {p:.3f}"
    note = (
        f"The change in conversion is statistically significant (two-proportion z-test, p {ptxt})."
        if sig
        else f"The change is not statistically significant at the {round(alpha * 100)}% level (p = {p:.3f}). It could be noise."
    )
    return {**base, "enough_data": True, "z": round(z, 3), "p_value": float(f"{p:.3g}"), "significant": sig, "note": note}


def suggested_windows(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    bounds = data_bounds(con)
    if not bounds:
        return []
    lo, hi = date.fromisoformat(bounds[0]), date.fromisoformat(bounds[1])
    out: list[dict[str, Any]] = []
    for a in recs.annotations_between(con, "0001-01-01", "9999-12-31"):
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


def summarize_window(
    con: duckdb.DuckDBPyConnection, f: Filters, frm: str, to: str, ctx: an.Ctx | None = None
) -> dict[str, Any]:  # fmt: skip
    """`WindowSummary` of docs/api-contract.md for one window."""
    ctx = ctx or an.load_ctx()
    names = {s["id"]: s["name"] for s in an.stage_defs()}
    w = resolve_window(con, frm, to)
    if f.segment == "humans":
        h = an.totals(con, ctx, f, w, segment="humans")
        return {"window": w.as_dict(), "sessions": h["sessions"], "converted": h["converted"],
                "conversion": h["converted"] / h["sessions"] if h["sessions"] else 0.0, "agent_revenue_inr": 0,
                "risk_inr": dict(ZERO_RISK), "funnel": an.funnel_series("humans", an.reach(con, ctx, f, w, "humans"), names),
                "blocker_shares": []}  # fmt: skip
    t = an.totals(con, ctx, f, w)
    res = an.compute_impact(con, ctx, f, w)
    return {
        "window": w.as_dict(), "sessions": t["sessions"], "converted": t["converted"],
        "conversion": t["converted"] / t["sessions"] if t["sessions"] else 0.0, "agent_revenue_inr": round(t["revenue"], 2),
        "risk_inr": res.risk_total(), "funnel": an.funnel_series(f.segment, an.reach(con, ctx, f, w, f.segment), names),
        "blocker_shares": [{"blocker_id": i.blocker_id, "name": i.name, "sessions_blocked": i.sessions_blocked,
                            "share_of_failed": i.share_of_failed, "risk_base_inr": i.base} for i in res.items],
    }  # fmt: skip


def compare_windows(
    con: duckdb.DuckDBPyConnection, a_from: str, a_to: str, b_from: str, b_to: str, *, segment: str = "all_agents",
    operator: str | None = None, agent_class: str | None = None,
) -> dict[str, Any]:  # fmt: skip
    """Compare window A (before) with window B (after) under identical filters. Dates are `YYYY-MM-DD`, inclusive."""
    f = Filters(None, None, segment, operator or None, agent_class or None)
    ctx = an.load_ctx()
    a = summarize_window(con, f, a_from, a_to, ctx)
    b = summarize_window(con, f, b_from, b_to, ctx)
    return {
        "segment": f.segment, "a": a, "b": b,
        "delta": {
            "sessions": b["sessions"] - a["sessions"], "conversion_pp": (b["conversion"] - a["conversion"]) * 100,
            "conversion_relative": b["conversion"] / a["conversion"] - 1 if a["conversion"] else None,
            "agent_revenue_inr": b["agent_revenue_inr"] - a["agent_revenue_inr"],
            "risk_base_inr": b["risk_inr"]["base"] - a["risk_inr"]["base"],
        },
        "significance": two_proportion_z(a["converted"], a["sessions"], b["converted"], b["sessions"], ctx.min_sessions),
        "suggested_windows": suggested_windows(con),
    }  # fmt: skip


def blocker_deltas(cmp: dict[str, Any]) -> list[dict[str, Any]]:
    """Per blocker: sessions blocked and base risk before -> after, largest improvement first."""
    before = {s["blocker_id"]: s for s in cmp["a"]["blocker_shares"]}
    after = {s["blocker_id"]: s for s in cmp["b"]["blocker_shares"]}
    rows = []
    for bid in before.keys() | after.keys():
        x, y = before.get(bid), after.get(bid)
        rows.append({
            "blocker_id": bid, "name": (x or y or {}).get("name", bid),
            "sessions_before": x["sessions_blocked"] if x else 0, "sessions_after": y["sessions_blocked"] if y else 0,
            "risk_before_inr": x["risk_base_inr"] if x else 0, "risk_after_inr": y["risk_base_inr"] if y else 0,
        })  # fmt: skip
    rows.sort(key=lambda r: (r["risk_after_inr"] - r["risk_before_inr"], r["blocker_id"]))
    return rows


def before_after(
    con: duckdb.DuckDBPyConnection, *, segment: str = "all_agents", operator: str | None = None,
    agent_class: str | None = None, annotation_id: str | None = None,
) -> dict[str, Any] | None:  # fmt: skip
    """Compare the windows around a fix (default: the first config_change / marked_fixed annotation).

    Returns `{annotation_id, label, compare, headline, blocker_deltas, control}`; `control` is the human conversion in
    the same two windows, shown for reference (in the synthetic scenario the fixes also help humans a little, so it is
    not a flat baseline). `None` when no annotation yields a window pair.
    """
    options = suggested_windows(con)
    if annotation_id:
        options = [o for o in options if o["annotation_id"] == annotation_id]
    if not options:
        return None
    w = options[0]
    cmp = compare_windows(con, w["a"]["from"], w["a"]["to"], w["b"]["from"], w["b"]["to"], segment=segment,
                          operator=operator, agent_class=agent_class)  # fmt: skip
    ctrl = compare_windows(con, w["a"]["from"], w["a"]["to"], w["b"]["from"], w["b"]["to"], segment="humans")
    a, b, d = cmp["a"], cmp["b"], cmp["delta"]
    return {
        "annotation_id": w["annotation_id"], "label": w["label"], "compare": cmp,
        "headline": {
            "conversion_before": a["conversion"], "conversion_after": b["conversion"], "conversion_pp": d["conversion_pp"],
            "conversion_relative": d["conversion_relative"], "agent_revenue_before_inr": a["agent_revenue_inr"],
            "agent_revenue_after_inr": b["agent_revenue_inr"], "risk_before_inr": a["risk_inr"]["base"],
            "risk_after_inr": b["risk_inr"]["base"], "significant": cmp["significance"]["significant"],
            "p_value": cmp["significance"]["p_value"], "sessions_before": a["sessions"], "sessions_after": b["sessions"],
        },
        "blocker_deltas": blocker_deltas(cmp),
        "control": {
            "humans_conversion_before": ctrl["a"]["conversion"], "humans_conversion_after": ctrl["b"]["conversion"],
            "humans_sessions_before": ctrl["a"]["sessions"], "humans_sessions_after": ctrl["b"]["sessions"],
        },
    }  # fmt: skip


__all__ = ["Window", "before_after", "blocker_deltas", "compare_windows", "suggested_windows", "two_proportion_z"]
