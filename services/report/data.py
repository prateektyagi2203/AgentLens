"""Collect everything the Agent Readiness Report shows into one plain dict (so md / html / tests share the numbers).

Numbers come from the same functions the dashboard uses (`routers.analytics`, `compare`), never from ground truth.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import duckdb
from agentlens import settings
from agentlens.compare import before_after
from agentlens.identify.constants import HONEST_LIMITATION
from agentlens.routers import analytics as an
from agentlens.routers import recs
from agentlens.routers.deps import Filters, parse_filters, resolve_window

TOP_BLOCKERS = 5
TOP_FIXES = 3
VERDICT_LABEL = {
    "confirmed": "Confirmed", "not_confirmed": "Not reproduced", "inconclusive": "Inconclusive",
}  # fmt: skip
SEGMENT_LABEL = {
    "all_agents": "all agents", "verified": "verified agents", "declared": "declared agents",
    "suspected": "suspected agents", "humans": "humans",
}  # fmt: skip


def _latest_replays(con: duckdb.DuckDBPyConnection) -> dict[str, dict[str, Any]]:
    rows = con.execute(
        "SELECT replay_id, blocker_id, mode, status, started_at, steps_json, verdict_explanation FROM replays "
        "WHERE status IN ('completed', 'failed') ORDER BY started_at, replay_id"
    ).fetchall()  # fmt: skip
    out: dict[str, dict[str, Any]] = {}
    for rid, bid, mode, status, started, steps_json, explanation in rows:
        doc: Any = {}
        try:
            doc = json.loads(steps_json) if steps_json else {}
        except ValueError:
            doc = {}
        doc = doc if isinstance(doc, dict) else {}
        verdict = doc.get("verdict") if status == "completed" else None
        out[bid] = {
            "replay_id": rid, "blocker_id": bid, "mode": mode, "status": status,
            "verdict": verdict if verdict in VERDICT_LABEL else "inconclusive",
            "explanation": explanation or "", "steps": len(doc.get("steps") or []),
            "user_agent": doc.get("user_agent") or "", "signed_requests": bool(doc.get("signed_requests")),
            "started_at": started.strftime("%Y-%m-%d %H:%M UTC") if started else None,
        }  # fmt: skip
    return out


def collect(con: duckdb.DuckDBPyConnection, filters: dict[str, str | None] | None = None) -> dict[str, Any]:
    """The report model. `filters` keys: from, to, segment, operator, agent_class (all optional)."""
    flt = filters or {}
    f: Filters = parse_filters(flt.get("from"), flt.get("to"), flt.get("segment"), flt.get("operator"), flt.get("agent_class"))
    ctx = an.load_ctx()
    w = resolve_window(con, f.from_, f.to)
    names = {s["id"]: s["name"] for s in an.stage_defs()}
    seg = f.segment if f.segment != "humans" else "all_agents"
    fa = Filters(f.from_, f.to, seg, f.operator, f.agent_class)

    agents = an.totals(con, ctx, fa, w)
    humans = an.totals(con, ctx, fa, w, segment="humans", filters=False)
    total_sessions = agents["sessions"] + humans["sessions"]
    res = an.compute_impact(con, ctx, fa, w)
    risk = res.risk_total()
    priced = [i for i in res.items if i.blocker_id != "B99"]
    b99 = res.get("B99")
    replays = _latest_replays(con)
    stored = recs.stored_recs(con)

    blockers = [{
        "blocker_id": i.blocker_id, "name": i.name, "stage": i.stage, "stage_name": names.get(i.stage, i.stage),
        "sessions_blocked": i.sessions_blocked, "share_of_failed": i.share_of_failed,
        "risk_low": i.low, "risk_base": i.base, "risk_high": i.high, "effort": i.effort, "owner": i.owner,
        "low_confidence": i.low_confidence, "replay": replays.get(i.blocker_id),
    } for i in priced[:TOP_BLOCKERS]]  # fmt: skip

    fixes = []
    for i in sorted(priced, key=lambda x: (-x.priority_score, x.blocker_id))[:TOP_FIXES]:
        meta = an.blocker_meta(ctx, i.blocker_id)
        rec = stored.get(i.blocker_id) or {}
        body = rec.get("body") or {}
        fixes.append({
            "blocker_id": i.blocker_id, "name": i.name, "fix": meta["fix"], "how_to_verify": meta["how_to_verify"],
            "effort": i.effort, "owner": i.owner, "risk_base": i.base, "status": rec.get("status") or "open",
            "explanation": body.get("llm_explanation") or "",
        })  # fmt: skip

    cov = (agents["tiers"]["verified"] + agents["tiers"]["declared"]) / agents["sessions"] if agents["sessions"] else 0.0
    ba = None
    if f.segment != "humans":
        try:
            ba = before_after(con, segment=f.segment, operator=f.operator, agent_class=f.agent_class)
        except Exception:  # noqa: BLE001 - the report must still render if the comparison cannot be built
            ba = None

    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "currency": "INR", "demo_mode": settings.demo_mode(),
        "window": w.as_dict(), "segment": f.segment, "segment_label": SEGMENT_LABEL.get(f.segment, f.segment),
        "operator": f.operator, "agent_class": f.agent_class, "has_data": total_sessions > 0,
        "headline": {
            "total_sessions": total_sessions, "agent_sessions": agents["sessions"], "human_sessions": humans["sessions"],
            "agent_share": agents["sessions"] / total_sessions if total_sessions else 0.0,
            "agent_conversion": agents["converted"] / agents["sessions"] if agents["sessions"] else 0.0,
            "human_conversion": humans["converted"] / humans["sessions"] if humans["sessions"] else 0.0,
            "agent_revenue": round(agents["revenue"]), "agent_converted": agents["converted"],
            "risk_low": risk["low"], "risk_base": risk["base"], "risk_high": risk["high"],
            "identity_coverage": cov, "tiers": agents["tiers"],
            "failed_agent_sessions": agents["failed"], "diagnosed_share": res.coverage,
            "unknown_share": b99.share_of_failed if b99 else 0.0,
        },
        "funnel": {
            "stages": [{"id": s["id"], "name": s["name"]} for s in an.stage_defs()],
            "agents": an.funnel_series("all_agents", an.reach(con, ctx, fa, w, "all_agents"), names),
            "humans": an.funnel_series("humans", an.reach(con, ctx, fa, w, "humans"), names),
        },
        "blockers": blockers, "fixes": fixes, "replays": sorted(replays.values(), key=lambda r: r["blocker_id"]),
        "before_after": ba,
        "assumptions": {
            "recoverable_rate": ctx.impact["recoverable_rate"], "p_stage_band": ctx.impact["p_stage_band"],
            "aov_inr": round(res.aov), "scale_k": round(res.k, 2), "window_days": w.days,
            "min_sample": ctx.impact["min_sample"],
        },
        "limitation": HONEST_LIMITATION,
    }  # fmt: skip
