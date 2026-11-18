"""Replays: list, detail, screenshots and the replay trigger (delegates to `agentlens.replay.runner` when present)."""

from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
from fastapi import APIRouter, Body, Depends
from fastapi.responses import FileResponse, JSONResponse

from . import analytics as an
from . import runs
from .deps import DB, ApiError, get_read, iso, not_found

router = APIRouter()

REPLAY_COLUMNS = "replay_id, blocker_id, source_session_id, mode, status, started_at, finished_at, steps_json, evidence_dir, verdict_explanation"
STATUSES = {"queued", "running", "completed", "failed"}


def _doc(steps_json: str | None) -> dict[str, Any]:
    """`steps_json` is an object written by the runner; a bare list of steps is tolerated."""
    if not steps_json:
        return {}
    try:
        doc = json.loads(steps_json)
    except (TypeError, ValueError):
        return {}
    if isinstance(doc, list):
        return {"steps": doc}
    return doc if isinstance(doc, dict) else {}


def replay_row(ctx: an.Ctx, r: tuple[Any, ...]) -> dict[str, Any]:
    rid, bid, sid, mode, status, started, finished, steps_json, _dir, expl = r
    doc = _doc(steps_json)
    status = status if status in STATUSES else "failed"
    verdict = an.replay_verdict(steps_json) if status == "completed" else None
    steps = doc.get("steps")
    return {
        "replay_id": rid, "blocker_id": bid, "blocker_name": an.blocker_name(ctx, bid) or bid, "source_session_id": sid or "",
        "mode": mode if mode in ("fetch", "browser") else "fetch", "status": status,
        "verdict": verdict or ("inconclusive" if status == "completed" else None),
        "started_at": iso(started), "finished_at": iso(finished), "steps_count": len(steps) if isinstance(steps, list) else 0,
        "verdict_explanation": expl or "",
    }  # fmt: skip


def replay_rows_for_blocker(cur: duckdb.DuckDBPyConnection, ctx: an.Ctx, blocker_id: str) -> list[dict[str, Any]]:
    rows = cur.execute(
        f"SELECT {REPLAY_COLUMNS} FROM replays WHERE blocker_id = ? ORDER BY started_at DESC, replay_id", [blocker_id]
    ).fetchall()
    return [replay_row(ctx, r) for r in rows]


@router.get("/replays")
def list_replays(cur: duckdb.DuckDBPyConnection = Depends(get_read)) -> dict[str, Any]:
    ctx = an.load_ctx()
    rows = cur.execute(f"SELECT {REPLAY_COLUMNS} FROM replays ORDER BY started_at DESC, replay_id").fetchall()
    return {"items": [replay_row(ctx, r) for r in rows]}


def _step(i: int, s: dict[str, Any]) -> dict[str, Any]:
    return {
        "n": int(s.get("n", i + 1)), "action": str(s.get("action", "")), "method": s.get("method"), "url": str(s.get("url", "")),
        "status": s.get("status"), "duration_ms": int(s.get("duration_ms") or 0), "note": str(s.get("note", "")),
        "screenshot_url": s.get("screenshot_url"),
    }  # fmt: skip


def _log(e: dict[str, Any]) -> dict[str, Any]:
    return {
        "ts": e.get("ts", ""), "method": str(e.get("method", "GET")), "url": str(e.get("url", "")), "status": int(e.get("status") or 0),
        "duration_ms": int(e.get("duration_ms") or 0), "error_code": e.get("error_code"),
    }  # fmt: skip


@router.get("/replays/{replay_id}")
def replay_detail(replay_id: str, cur: duckdb.DuckDBPyConnection = Depends(get_read)) -> dict[str, Any]:
    ctx = an.load_ctx()
    r = an.one_row(cur, f"SELECT {REPLAY_COLUMNS} FROM replays WHERE replay_id = ?", [replay_id])
    if r is None:
        raise not_found(f"Replay {replay_id} not found")
    doc = _doc(r[7])
    row = replay_row(ctx, r)
    steps = [_step(i, s) for i, s in enumerate(doc.get("steps") or []) if isinstance(s, dict)]
    log = [_log(e) for e in doc.get("network_log") or [] if isinstance(e, dict)]
    return {
        "replay": row, "user_agent": str(doc.get("user_agent", "")), "signed_requests": bool(doc.get("signed_requests", False)),
        "steps": steps, "network_log": log, "explanation": row["verdict_explanation"],
    }  # fmt: skip


@router.get("/replays/{replay_id}/screenshots/{filename}")
def screenshot(replay_id: str, filename: str, cur: duckdb.DuckDBPyConnection = Depends(get_read)) -> FileResponse:
    row = an.one_row(cur, "SELECT evidence_dir FROM replays WHERE replay_id = ?", [replay_id])
    if row is None or not row[0] or Path(filename).name != filename:
        raise not_found("Screenshot not found")
    root = Path(row[0]).resolve()
    path = (root / filename).resolve()
    if root not in path.parents or not path.is_file():
        raise not_found("Screenshot not found")
    return FileResponse(path)


def _runner() -> Any:
    try:
        return importlib.import_module("agentlens.replay.runner")
    except ImportError:
        return None


@router.post("/replays/run", status_code=202)
def run_replays(body: dict[str, Any] | None = Body(default=None)) -> JSONResponse:
    b = body or {}
    ctx = an.load_ctx()
    errors: dict[str, str] = {}
    bid, top_n = b.get("blocker_id"), b.get("top_n")
    if bid is not None and (not isinstance(bid, str) or bid not in ctx.catalog or bid == "B99"):
        errors["blocker_id"] = "unknown blocker"
    if top_n is not None and (isinstance(top_n, bool) or not isinstance(top_n, int) or not 1 <= top_n <= 20):
        errors["top_n"] = "must be an integer between 1 and 20"
    if errors:
        raise ApiError(422, "validation_error", "Invalid replay request", errors)
    runner = _runner()
    if runner is None or not hasattr(runner, "run_replays"):
        raise ApiError(501, "not_implemented", "The replay runner is not available in this build")

    def work(run_id: str, rec: dict[str, Any]) -> None:
        steps = {s["name"]: s for s in rec["steps"]}

        def on_step(name: str, status: str = "running", message: str | None = None) -> None:
            step = steps.get(name)
            if step is None:
                return
            now = datetime.now(UTC).replace(tzinfo=None)
            if step["status"] == "pending":
                step["started"] = now
            step["status"] = status if status in ("running", "succeeded", "failed") else "running"
            if status in ("succeeded", "failed"):
                step["finished"] = now
            if message:
                step["message"] = message

        cur = DB.connection().cursor()
        try:
            result = runner.run_replays(cur, blocker_id=bid, top_n=top_n, on_step=on_step)
        finally:
            cur.close()
        now = datetime.now(UTC).replace(tzinfo=None)
        for s in rec["steps"]:
            if s["status"] in ("pending", "running"):
                s["status"], s["finished"] = "succeeded", now
        rec["counts"] = {f"replay.{k}": v for k, v in result.items()} if isinstance(result, dict) else {}

    run_id = runs.start_run("replay", work, list(runs.REPLAY_STEPS))
    return JSONResponse({"run_id": run_id, "status": "queued"}, status_code=202)
