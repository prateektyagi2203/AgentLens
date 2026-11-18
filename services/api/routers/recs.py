"""Recommendation shaping shared by /recommendations, /overview and /blockers/{id}."""

from __future__ import annotations

import json
from typing import Any

import duckdb

from .analytics import BlockerImpact, Ctx, ImpactResult, blocker_meta


def rec_id_of(blocker_id: str) -> str:
    return f"rec_{blocker_id}"


def blocker_of_rec(rec_id: str) -> str:
    """Accept rec_B05 (wire form) and rec-B05 (stored form)."""
    return rec_id.replace("rec_", "", 1).replace("rec-", "", 1)


ANNOTATION_SQL = "SELECT annotation_id, ts, type, label, details_json FROM annotations"


def annotation(row: tuple[Any, ...]) -> dict[str, Any]:
    from .deps import iso

    aid, ts, typ, label, details = row
    try:
        doc = json.loads(details) if details else {}
    except ValueError:
        doc = {}
    return {"annotation_id": aid, "ts": iso(ts), "type": typ, "label": label, "details": doc if isinstance(doc, dict) else {}}


def annotations_between(cur: duckdb.DuckDBPyConnection, from_day: str, to_day: str) -> list[dict[str, Any]]:
    rows = cur.execute(
        f"{ANNOTATION_SQL} WHERE CAST(ts AS DATE) BETWEEN ? AND ? ORDER BY ts, annotation_id", [from_day, to_day]
    ).fetchall()
    return [annotation(r) for r in rows]


def stored_recs(cur: duckdb.DuckDBPyConnection) -> dict[str, dict[str, Any]]:
    rows = cur.execute(
        "SELECT blocker_id, rec_id, run_id, title, body, status, fixed_annotation_id FROM recommendations"
    ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for bid, rid, run_id, title, body, status, ann in rows:
        try:
            doc = json.loads(body) if body else {}
        except ValueError:
            doc = {"what": body}
        out[bid] = {"rec_id": rid, "run_id": run_id, "title": title, "body": doc if isinstance(doc, dict) else {}, "status": status, "ann": ann}
    return out


def build(ctx: Ctx, item: BlockerImpact, stored: dict[str, dict[str, Any]]) -> dict[str, Any]:
    meta = blocker_meta(ctx, item.blocker_id)
    row = stored.get(item.blocker_id)
    doc = row["body"] if row else {}
    title = (row or {}).get("title") or f"{meta['name']}: {meta['fix']}".split(". ")[0][:140]
    fixed = bool(row and (row["status"] == "fixed" or row["ann"]))
    return {
        "rec_id": rec_id_of(item.blocker_id), "run_id": (row or {}).get("run_id") or "", "blocker_id": item.blocker_id,
        "blocker_name": meta["name"], "title": title, "body": doc.get("what") or meta["fix"],
        "why_it_helps": doc.get("why_it_helps") or meta["description"],
        "how_to_verify": doc.get("how_to_verify") or meta["how_to_verify"],
        "verify_metric": doc.get("verify_metric") or f"Agent sessions ending with {item.blocker_id} per day",
        "effort": item.effort, "owner": item.owner, "priority_score": item.priority_score, "risk_inr_base": item.base,
        "status": "fixed" if fixed else "open", "fixed_annotation_id": (row or {}).get("ann"),
        "llm_explanation": doc.get("llm_explanation"),
    }  # fmt: skip


def recommendations(ctx: Ctx, res: ImpactResult, stored: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    items = [build(ctx, i, stored) for i in res.items if i.blocker_id != "B99"]
    items.sort(key=lambda r: (-r["priority_score"], -r["risk_inr_base"], r["blocker_id"]))
    return items
