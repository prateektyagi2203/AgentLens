"""Blockers (list + detail), recommendations (+ mark fixed) and annotations."""

from __future__ import annotations

import json
import uuid
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Any

import duckdb
from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from . import analytics as an
from . import core, recs
from .deps import DB, Filters, filters_dep, get_read, not_found, resolve_window, validation_error
from .replays import replay_rows_for_blocker

router = APIRouter()

ANNOTATION_TYPES = ("config_change", "marked_fixed", "note")


def known_blocker(ctx: an.Ctx, blocker_id: str) -> bool:
    return blocker_id in ctx.catalog


@router.get("/blockers")
def blockers(f: Filters = Depends(filters_dep), cur: duckdb.DuckDBPyConnection = Depends(get_read)) -> dict[str, Any]:
    ctx = an.load_ctx()
    w = resolve_window(cur, f.from_, f.to)
    res = an.compute_impact(cur, ctx, f, w)
    imp = ctx.impact
    return {
        "window": w.as_dict(), "total_risk_base_inr": res.risk_total()["base"], "total_failed_agent_sessions": res.failed,
        "diagnosis_coverage": res.coverage,
        "assumptions": {
            "recoverable_rate": imp["recoverable_rate"], "p_stage_band": imp["p_stage_band"], "default_aov_inr": imp["default_aov_inr"],
            "window_days": w.days, "k": 30.0 / max(1, w.days), "min_sample": imp["min_sample"],
        },
        "items": [i.item() for i in res.items],
    }  # fmt: skip


def _evidence(cur: duckdb.DuckDBPyConnection, ctx: an.Ctx, f: Filters, w: Any, blocker_id: str, total: int) -> dict[str, Any]:
    where, params = an.population(ctx, f, w, alias="s")
    base = f"""
        FROM blocker_hits h JOIN sessions s ON s.session_id = h.session_id
        WHERE h.blocker_id = ? AND h.is_terminal AND s.terminal_blocker_id = ? AND NOT s.converted AND {where}"""
    bp = [blocker_id, blocker_id, *params]
    # the evidence summary ("POST /api/cart -> 409 PINCODE_REQUIRED") already carries status + error code, so no `requests` lookup
    rows = cur.execute(
        f"""SELECT json_extract_string(h.evidence_json, '$[0].request_id'),
                   regexp_replace(json_extract_string(h.evidence_json, '$[0].summary'), '[?].*| \\(.*\\)$', ''),
                   regexp_extract(json_extract_string(h.evidence_json, '$[0].summary'), '-> ([0-9]{{3}})( [A-Z][A-Z0-9_]*)?', ['st', 'ec']),
                   CASE WHEN h.evidence_json LIKE '%site_check%' THEN h.evidence_json END {base}""",
        bp,
    ).fetchall()
    code_counts: Counter[str] = Counter()
    example_counts: Counter[str] = Counter()
    example_rid: dict[str, str] = {}
    raw: list[str] = []
    for rid, summ, parts, blob in rows:
        status, ec = (parts or {}).get("st"), ((parts or {}).get("ec") or "").strip()
        if status:
            code_counts[ec or f"HTTP {status}"] += 1
        if summ is not None:
            example_counts[summ] += 1
            if summ not in example_rid or (rid is not None and rid < example_rid[summ]):
                example_rid[summ] = rid
        if blob is not None and len(raw) < 200:
            raw.append(blob)
    codes = sorted(code_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    examples = [(example_rid[s], s, n) for s, n in sorted(example_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]]
    names: set[str] = set()
    for blob in raw:
        try:
            names |= {e["check"] for e in json.loads(blob) if isinstance(e, dict) and e.get("type") == "site_check" and e.get("check")}
        except (TypeError, ValueError):
            continue
    checks = [c for c in core.site_checks_latest(cur, w.to) if c["check_name"] in names]
    return {
        "top_error_codes": [{"code": c, "count": int(n), "share": int(n) / total if total else 0.0} for c, n in codes],
        "example_requests": [{"request_id": rid, "summary": s, "count": int(n)} for rid, s, n in examples],
        "site_checks": checks,
    }  # fmt: skip


@router.get("/blockers/{blocker_id}")
def blocker_detail(
    blocker_id: str, f: Filters = Depends(filters_dep), cur: duckdb.DuckDBPyConnection = Depends(get_read)
) -> dict[str, Any]:  # fmt: skip
    ctx = an.load_ctx()
    if not known_blocker(ctx, blocker_id):
        raise not_found(f"Unknown blocker {blocker_id}")
    w = resolve_window(cur, f.from_, f.to)
    res = an.compute_impact(cur, ctx, f, w)
    item = res.get(blocker_id) or an.empty_item(ctx, blocker_id, an.replay_status_map(cur).get(blocker_id, "not_run"))
    meta = an.blocker_meta(ctx, blocker_id)
    where, params = an.population(ctx, f, w)
    term = f"{where} AND terminal_blocker_id = ? AND NOT converted"
    tp = [*params, blocker_id]
    daily = {
        r[0].isoformat(): int(r[1])
        for r in cur.execute(f"SELECT CAST(start_ts AS DATE), count(*) FROM sessions WHERE {term} GROUP BY 1", tp).fetchall()
    }
    trend = []
    day = date.fromisoformat(w.from_)
    while day <= date.fromisoformat(w.to):
        trend.append({"date": day.isoformat(), "sessions_blocked": daily.get(day.isoformat(), 0)})
        day += timedelta(days=1)
    sample = cur.execute(f"SELECT {an.session_cols()} FROM sessions WHERE {term} ORDER BY start_ts DESC, session_id LIMIT 6", tp).fetchall()
    rule = _rule_title(blocker_id)
    stored = recs.stored_recs(cur)
    return {
        "window": w.as_dict(), "blocker": item.item(), "description": meta["description"],
        "detection": f"Rule {blocker_id} ({rule}) on the request log; evidence below." if rule else meta["description"],
        "evidence": _evidence(cur, ctx, f, w, blocker_id, item.sessions_blocked),
        "risk_breakdown": {
            "sessions_blocked": item.sessions_blocked, "recoverable_rate": float(ctx.impact["recoverable_rate"]["base"]),
            "p_stage": item.p_stage, "aov_inr": res.aov if res.converted else float(ctx.impact["default_aov_inr"]), "k": res.k,
        },
        "trend": trend, "sample_sessions": [an.session_row(ctx, r) for r in sample],
        "replays": replay_rows_for_blocker(cur, ctx, blocker_id),
        "recommendation": None if blocker_id == "B99" else recs.build(ctx, item, stored),
    }  # fmt: skip


def _rule_title(blocker_id: str) -> str | None:
    try:
        from ..diagnosis.rules import RULES

        return RULES[blocker_id].title if blocker_id in RULES else None
    except ImportError:
        return None


# ---------------------------------------------------------------- recommendations
@router.get("/recommendations")
def recommendations(f: Filters = Depends(filters_dep), cur: duckdb.DuckDBPyConnection = Depends(get_read)) -> dict[str, Any]:
    ctx = an.load_ctx()
    w = resolve_window(cur, f.from_, f.to)
    res = an.compute_impact(cur, ctx, f, w)
    return {"items": recs.recommendations(ctx, res, recs.stored_recs(cur))}


@router.patch("/recommendations/{rec_id}")
def mark_fixed(
    rec_id: str, body: dict[str, Any] | None = Body(default=None), f: Filters = Depends(filters_dep),
    cur: duckdb.DuckDBPyConnection = Depends(get_read),
) -> dict[str, Any]:  # fmt: skip
    ctx = an.load_ctx()
    bid = recs.blocker_of_rec(rec_id)
    if bid == "B99" or not known_blocker(ctx, bid):
        raise not_found(f"Recommendation {rec_id} not found")
    if (body or {}).get("status") != "fixed":
        raise validation_error("status must be 'fixed'", {"status": "must be 'fixed'"})
    meta = an.blocker_meta(ctx, bid)
    with DB.write() as wr:
        row = wr.execute("SELECT fixed_annotation_id, title FROM recommendations WHERE blocker_id = ?", [bid]).fetchone()
        ann_id = row[0] if row else None
        existing = wr.execute(f"{recs.ANNOTATION_SQL} WHERE annotation_id = ?", [ann_id]).fetchone() if ann_id else None
        if existing is None:
            title = (row[1] if row and row[1] else None) or f"{meta['name']}: {meta['fix']}".split(". ")[0][:140]
            ann_id = f"ann_{uuid.uuid4().hex[:8]}"
            wr.execute("BEGIN")
            try:
                wr.execute(
                    "INSERT INTO annotations (annotation_id, ts, type, label, details_json) VALUES (?, ?, 'marked_fixed', ?, ?)",
                    [ann_id, datetime.now(UTC).replace(tzinfo=None), f"Marked fixed: {title}",
                     json.dumps({"blocker_id": bid, "rec_id": recs.rec_id_of(bid)})],
                )  # fmt: skip
                if row:
                    wr.execute("UPDATE recommendations SET status = 'fixed', fixed_annotation_id = ? WHERE blocker_id = ?", [ann_id, bid])
                else:
                    wr.execute(
                        """INSERT INTO recommendations (rec_id, run_id, blocker_id, title, body, effort, owner, priority_score, status,
                                                         fixed_annotation_id) VALUES (?, '', ?, ?, '{}', ?, ?, 0, 'fixed', ?)""",
                        [f"rec-{bid}", bid, title, meta["effort"], meta["owner"], ann_id],
                    )
                wr.execute("COMMIT")
            except BaseException:
                wr.execute("ROLLBACK")
                raise
            existing = wr.execute(f"{recs.ANNOTATION_SQL} WHERE annotation_id = ?", [ann_id]).fetchone()
        elif row and row[0]:
            wr.execute("UPDATE recommendations SET status = 'fixed' WHERE blocker_id = ?", [bid])
    assert existing is not None
    w = resolve_window(cur, f.from_, f.to)
    res = an.compute_impact(cur, ctx, f, w)
    item = res.get(bid) or an.empty_item(ctx, bid, an.replay_status_map(cur).get(bid, "not_run"))
    return {"recommendation": recs.build(ctx, item, recs.stored_recs(cur)), "annotation": recs.annotation(existing)}


# ---------------------------------------------------------------- annotations
@router.get("/annotations")
def list_annotations(cur: duckdb.DuckDBPyConnection = Depends(get_read)) -> dict[str, Any]:
    rows = cur.execute(f"{recs.ANNOTATION_SQL} ORDER BY ts, annotation_id").fetchall()
    return {"items": [recs.annotation(r) for r in rows]}


def _parse_ts(value: Any) -> datetime | None:
    if value is None or value == "":
        return datetime.now(UTC).replace(tzinfo=None)
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts.astimezone(UTC).replace(tzinfo=None) if ts.tzinfo else ts


@router.post("/annotations", status_code=201)
def create_annotation(body: dict[str, Any] | None = Body(default=None)) -> JSONResponse:
    b = body or {}
    errors: dict[str, str] = {}
    label, typ = b.get("label"), b.get("type")
    if not isinstance(label, str) or not label.strip():
        errors["label"] = "required"
    if typ is None or typ == "":
        errors["type"] = "required"
    elif typ not in ANNOTATION_TYPES:
        errors["type"] = f"must be one of {', '.join(ANNOTATION_TYPES)}"
    ts = _parse_ts(b.get("ts"))
    if ts is None:
        errors["ts"] = "must be an ISO-8601 timestamp"
    details = b.get("details", {})
    if details is not None and not isinstance(details, dict):
        errors["details"] = "must be an object"
    if errors:
        raise validation_error("Invalid annotation", errors)
    ann_id = f"ann_{uuid.uuid4().hex[:8]}"
    with DB.write() as wr:
        wr.execute(
            "INSERT INTO annotations (annotation_id, ts, type, label, details_json) VALUES (?, ?, ?, ?, ?)",
            [ann_id, ts, typ, str(label).strip(), json.dumps(details or {})],
        )
        row = wr.execute(f"{recs.ANNOTATION_SQL} WHERE annotation_id = ?", [ann_id]).fetchone()
    assert row is not None
    return JSONResponse(recs.annotation(row), status_code=201)
