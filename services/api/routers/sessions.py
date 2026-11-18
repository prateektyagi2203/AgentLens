"""GET /sessions and GET /sessions/{id}."""

from __future__ import annotations

import json
from typing import Any

import duckdb
from fastapi import APIRouter, Depends

from .. import funnel
from . import analytics as an
from .agents import SIG_RANK
from .deps import STAGE_IDS, ApiError, Filters, filters_dep, get_read, iso, not_found, resolve_window

router = APIRouter()

SORTS = {"start_ts": "start_ts", "duration_s": "duration_s", "request_count": "request_count", "order_value_inr": "order_value"}
TIER_VALUES = ("verified", "declared", "suspected", "human")


@router.get("/sessions")
def sessions(
    f: Filters = Depends(filters_dep),
    page: int = 1,
    page_size: int = 25,
    q: str | None = None,
    identity_tier: str | None = None,
    blocker_id: str | None = None,
    max_stage: str | None = None,
    converted: str | None = None,
    sort: str = "start_ts",
    order: str = "desc",
    cur: duckdb.DuckDBPyConnection = Depends(get_read),
) -> dict[str, Any]:
    errors: dict[str, str] = {}
    if page < 1:
        errors["page"] = "must be >= 1"
    if page_size < 1:
        errors["page_size"] = "must be >= 1"
    if identity_tier is not None and identity_tier not in TIER_VALUES:
        errors["identity_tier"] = f"must be one of {', '.join(TIER_VALUES)}"
    if max_stage is not None and max_stage not in STAGE_IDS:
        errors["max_stage"] = "must be S1..S8"
    if converted is not None and converted not in ("true", "false"):
        errors["converted"] = "must be true or false"
    if sort not in SORTS:
        errors["sort"] = f"must be one of {', '.join(SORTS)}"
    if order not in ("asc", "desc"):
        errors["order"] = "must be asc or desc"
    if errors:
        raise ApiError(422, "validation_error", "Invalid query parameters", errors)
    page_size = min(page_size, 100)

    ctx = an.load_ctx()
    w = resolve_window(cur, f.from_, f.to)
    where, params = an.population(ctx, f, w)
    conds = [where]
    if identity_tier:
        conds.append("COALESCE(identity_tier, 'human') = ?")
        params.append(identity_tier)
    if blocker_id:
        conds.append("terminal_blocker_id = ?")
        params.append(blocker_id)
    if max_stage:
        conds.append("max_stage = ?")
        params.append(max_stage)
    if converted is not None:
        conds.append("converted = ?")
        params.append(converted == "true")
    if q and q.strip():
        needle = q.strip().lower()
        ids = [b for b in ctx.catalog if needle in str(an.blocker_name(ctx, b) or "").lower()]
        fields = ("session_id", "operator", "agent_name", "entry_page", "exit_page", "terminal_blocker_id")
        parts = [f"contains(lower(COALESCE({c}, '')), ?)" for c in fields]
        params += [needle] * len(fields)
        if ids:
            parts.append(f"terminal_blocker_id IN ({', '.join('?' for _ in ids)})")
            params += ids
        conds.append("(" + " OR ".join(parts) + ")")
    clause = " AND ".join(conds)
    total = int(cur.execute(f"SELECT count(*) FROM sessions WHERE {clause}", params).fetchone()[0])  # type: ignore[index]
    direction = "ASC" if order == "asc" else "DESC"
    rows = cur.execute(
        f"""SELECT {an.session_cols()} FROM sessions WHERE {clause}
            ORDER BY {SORTS[sort]} {direction} NULLS LAST, session_id LIMIT ? OFFSET ?""",
        [*params, page_size, (page - 1) * page_size],
    ).fetchall()
    return {"window": w.as_dict(), "page": page, "page_size": page_size, "total": total, "items": [an.session_row(ctx, r) for r in rows]}


def _evidence(blob: str | None) -> list[dict[str, Any]]:
    try:
        items = json.loads(blob) if blob else []
    except ValueError:
        return []
    out: list[dict[str, Any]] = []
    for e in items if isinstance(items, list) else []:
        if not isinstance(e, dict):
            continue
        if e.get("type") == "request" and e.get("request_id"):
            out.append({"type": "request", "request_id": str(e["request_id"]), "summary": str(e.get("summary", ""))})
        elif e.get("type") == "site_check" and e.get("check"):
            out.append({"type": "site_check", "check": str(e["check"]), "result": e.get("result", "missing")})
    return out


@router.get("/sessions/{session_id}")
def session_detail(session_id: str, cur: duckdb.DuckDBPyConnection = Depends(get_read)) -> dict[str, Any]:
    ctx = an.load_ctx()
    row = an.one_row(cur, f"SELECT {an.session_cols()} FROM sessions WHERE session_id = ?", [session_id])
    if row is None:
        raise not_found(f"Session {session_id} not found")
    session = an.session_row(ctx, row)
    reqs = cur.execute(
        """SELECT request_id, ts, method, path, status, duration_ms, page_type, error_code, is_asset, user_agent, signature_status,
                  signature_agent, suspicion_score FROM requests WHERE session_id = ? ORDER BY ts, request_id""",
        [session_id],
    ).fetchall()
    cfg = an.yaml_cached("funnel")
    t0 = reqs[0][1] if reqs else None
    requests = []
    for rid, ts, method, path, status, dur, ptype, err, asset, *_rest in reqs:
        stage = None if asset else funnel.classify_request(method or "GET", path or "", status, cfg)[1]
        requests.append({
            "request_id": rid, "ts": iso(ts), "offset_ms": int((ts - t0).total_seconds() * 1000) if t0 and ts else 0,
            "method": method or "GET", "path": path or "", "status": int(status or 0), "duration_ms": int(dur or 0),
            "page_type": ptype, "error_code": err, "stage_id": stage, "is_asset": bool(asset),
        })  # fmt: skip
    statuses = [r[10] for r in reqs if r[10]]
    best = min(statuses, key=lambda s: SIG_RANK.index(s) if s in SIG_RANK else len(SIG_RANK)) if statuses else "none"
    sig_agent = next((r[11] for r in reqs if r[11]), None)
    scores = [float(r[12]) for r in reqs if r[12] is not None]
    stages = cur.execute(
        "SELECT stage_id, min(first_reached_ts) FROM session_stages WHERE session_id = ? GROUP BY 1 ORDER BY 2, 1", [session_id]
    ).fetchall()
    hits = cur.execute(
        "SELECT blocker_id, stage_id, confidence, is_terminal, evidence_json FROM blocker_hits WHERE session_id = ? "
        "ORDER BY is_terminal DESC, confidence DESC, blocker_id",
        [session_id],
    ).fetchall()
    replays = cur.execute("SELECT replay_id FROM replays WHERE source_session_id = ? ORDER BY started_at, replay_id", [session_id]).fetchall()
    return {
        "session": session,
        "identity": {
            "signature_status": best if best in an.SIGNATURE_STATUSES else "none", "signature_agent": sig_agent,
            "suspicion_score": max(scores) if scores else None, "user_agent": next((r[9] for r in reqs if r[9]), ""), "ip_match": None,
        },
        "requests": requests,
        "stage_events": [{"stage_id": s, "first_reached_ts": iso(ts)} for s, ts in stages],
        "fired_rules": [
            {"blocker_id": b, "name": an.blocker_name(ctx, b), "stage": st, "confidence": float(c or 0), "is_terminal": bool(t),
             "evidence": _evidence(ev)}
            for b, st, c, t, ev in hits
        ],
        "replay_ids": [r[0] for r in replays],
    }  # fmt: skip
