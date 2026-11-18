"""Runs: background pipeline / replay executions with an in-memory registry (and the `runs` table as history).

One run at a time across kinds: the pipeline and the replay runner both write, and DuckDB has a single writer. The worker
thread holds `DB.write_lock` for the whole run, so interactive writes (annotations, mark-fixed) wait or get a 409.
"""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import duckdb
from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from .. import db, pipeline
from .deps import DB, ApiError, get_read, iso, not_found

router = APIRouter()

REPLAY_STEPS = ("select", "replay", "verdict")
_STATUS = {"success": "succeeded", "succeeded": "succeeded", "failed": "failed", "running": "running"}


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Registry:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.runs: dict[str, dict[str, Any]] = {}
        self.order: list[str] = []

    def active(self) -> dict[str, Any] | None:
        return next((r for r in self.runs.values() if r["status"] in ("queued", "running")), None)

    def reset(self) -> None:
        with self.lock:
            self.runs.clear()
            self.order.clear()


REG = Registry()


def _new_record(run_id: str, kind: str, names: list[str]) -> dict[str, Any]:
    return {
        "run_id": run_id, "kind": kind, "status": "queued", "started": None, "finished": None, "error": None, "counts": {},
        "steps": [{"name": n, "status": "pending", "started": None, "finished": None, "message": None} for n in names],
        "seconds": [],
    }  # fmt: skip


def start_run(kind: str, worker: Callable[[str, dict[str, Any]], None], names: list[str], run_id: str | None = None) -> str:
    """Register + launch a run, or 409 if one is active. `worker(run_id, record)` does the work inside the thread."""
    with REG.lock:
        if REG.active() is not None:
            raise ApiError(409, "run_in_progress", f"A {REG.active()['kind']} run is already in progress")  # type: ignore[index]
        rid = run_id or uuid.uuid4().hex[:12]
        rec = _new_record(rid, kind, names)
        REG.runs[rid] = rec
        REG.order.append(rid)

    def target() -> None:
        with DB.write_lock:
            rec["status"], rec["started"] = "running", _now()
            try:
                worker(rid, rec)
                if rec["status"] == "running":
                    rec["status"] = "succeeded"
            except Exception as exc:  # the run record carries the failure; the thread must not die silently
                rec["status"], rec["error"] = "failed", f"{type(exc).__name__}: {exc}"
            finally:
                rec["finished"] = _now()
                DB.bump()

    threading.Thread(target=target, name=f"run-{rid}", daemon=True).start()
    return rid


def _to_run(rec: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": rec["run_id"], "kind": rec["kind"], "status": rec["status"], "started_at": iso(rec["started"]),
        "finished_at": iso(rec["finished"]), "error": rec["error"], "counts": rec["counts"],
        "steps": [
            {"name": s["name"], "status": s["status"], "started_at": iso(s["started"]), "finished_at": iso(s["finished"]),
             "message": s["message"]}
            for s in rec["steps"]
        ],
    }  # fmt: skip


def _flatten_counts(steps: list[dict[str, Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for s in steps:
        for k, v in (s.get("counts") or {}).items():
            if isinstance(v, int | float) and not isinstance(v, bool):
                out[f"{s['name']}.{k}"] = v
    return out


def run_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    """`runs` table row (run_id, started_at, finished_at, steps_json, status, counts_json) -> Run."""
    rid, started, finished, steps_json, status, _counts = row
    try:
        log = json.loads(steps_json) if steps_json else []
    except ValueError:
        log = []
    cursor = started
    steps = []
    for s in log:
        begin = cursor
        cursor = cursor + timedelta(seconds=float(s.get("seconds") or 0)) if cursor else None
        msg = s.get("error") or (", ".join(f"{k}={v}" for k, v in (s.get("counts") or {}).items())[:200] or None)
        steps.append({"name": s["name"], "status": _STATUS.get(s.get("status", ""), "pending"), "started_at": iso(begin),
                      "finished_at": iso(cursor), "message": msg})  # fmt: skip
    done = {s["name"] for s in steps}
    if status == "running":
        for n in pipeline.CANONICAL_ORDER:
            if n not in done:
                steps.append({"name": n, "status": "pending", "started_at": None, "finished_at": None, "message": None})
    failed = next((s for s in log if s.get("status") == "failed"), None)
    return {
        "run_id": rid, "kind": "pipeline", "status": _STATUS.get(status or "", "running"), "started_at": iso(started),
        "finished_at": iso(finished), "steps": steps, "counts": _flatten_counts(log), "error": failed.get("error") if failed else None,
    }  # fmt: skip


ROW_SQL = "SELECT run_id, started_at, finished_at, steps_json, status, counts_json FROM runs"


def get_run(cur: duckdb.DuckDBPyConnection, run_id: str) -> dict[str, Any] | None:
    rec = REG.runs.get(run_id)
    if rec is not None and (rec["status"] in ("succeeded", "failed") or rec["kind"] == "replay"):
        return _to_run(rec)
    row = db.one(cur, f"{ROW_SQL} WHERE run_id = ?", [run_id])
    if row is not None:
        run = run_from_row(row)
        if rec is not None and rec["status"] == "running":
            run["status"] = "running"
        return run
    return _to_run(rec) if rec is not None else None


def last_run(cur: duckdb.DuckDBPyConnection) -> dict[str, Any] | None:
    row = db.one(cur, f"{ROW_SQL} ORDER BY started_at DESC LIMIT 1")
    candidates: list[tuple[datetime, dict[str, Any]]] = []
    if row is not None and row[1] is not None:
        candidates.append((row[1], get_run(cur, row[0]) or run_from_row(row)))
    for rec in REG.runs.values():
        if rec["started"] is not None:
            candidates.append((rec["started"], get_run(cur, rec["run_id"]) or _to_run(rec)))
    active = REG.active()
    if active is not None and active["started"] is None:
        candidates.append((_now(), _to_run(active)))
    return max(candidates, key=lambda c: c[0])[1] if candidates else None


# ---------------------------------------------------------------- workers
def pipeline_worker(params: dict[str, Any]) -> Callable[[str, dict[str, Any]], None]:
    def work(run_id: str, rec: dict[str, Any]) -> None:
        cur = DB.connection().cursor()
        try:
            res = pipeline.run_steps(cur, None, {**params, "run_id": run_id})
        finally:
            cur.close()
        row = None
        with DB.read() as rd:
            row = db.one(rd, f"{ROW_SQL} WHERE run_id = ?", [run_id])
        if row is not None:
            done = run_from_row(row)
            rec["steps"] = [{"name": s["name"], "status": s["status"], "started": None, "finished": None, "message": s["message"]}
                            for s in done["steps"]]  # fmt: skip
            rec["counts"], rec["error"] = done["counts"], done["error"]
            for s, d in zip(rec["steps"], done["steps"], strict=False):
                s["started"] = _parse(d["started_at"])
                s["finished"] = _parse(d["finished_at"])
        rec["status"] = "succeeded" if res.ok else "failed"

    return work


def _parse(value: str | None) -> datetime | None:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ") if value else None


def pipeline_names() -> list[str]:
    return list(pipeline.CANONICAL_ORDER)


@router.post("/pipeline/run", status_code=202)
def run_pipeline(body: dict[str, Any] | None = Body(default=None)) -> JSONResponse:
    params = {k: v for k, v in (body or {}).items() if k in ("source", "fmt", "skip_site_probe", "llm_provider", "site_url") and v is not None}
    run_id = start_run("pipeline", pipeline_worker(params), pipeline_names())
    return JSONResponse({"run_id": run_id, "status": "queued"}, status_code=202)


@router.post("/ingest", status_code=202)
def ingest(body: dict[str, Any] | None = Body(default=None)) -> JSONResponse:
    """PRD 10.2 IN1: incremental ingest only (no identification or analysis). Same run model as the pipeline."""
    b = body or {}
    fmt = b.get("format", "jsonl")
    if fmt not in ("jsonl", "nginx_combined"):
        raise ApiError(422, "validation_error", "Invalid ingest request", {"format": "must be jsonl or nginx_combined"})

    def work(run_id: str, rec: dict[str, Any]) -> None:
        cur = DB.connection().cursor()
        try:
            res = pipeline.run_steps(cur, ["ingest"], {"source": b.get("source"), "fmt": fmt, "run_id": run_id})
        finally:
            cur.close()
        rec["counts"] = _flatten_counts(res.steps)
        rec["steps"] = [{"name": s["name"], "status": _STATUS.get(s["status"], "pending"), "started": None, "finished": None,
                         "message": s.get("error")} for s in res.steps]  # fmt: skip
        rec["error"] = next((s.get("error") for s in res.steps if s["status"] == "failed"), None)
        rec["status"] = "succeeded" if res.ok else "failed"

    run_id = start_run("pipeline", work, ["ingest"])
    return JSONResponse({"run_id": run_id, "status": "queued"}, status_code=202)


@router.get("/runs/{run_id}")
def read_run(run_id: str, cur: duckdb.DuckDBPyConnection = Depends(get_read)) -> dict[str, Any]:
    run = get_run(cur, run_id)
    if run is None:
        raise not_found(f"Run {run_id} not found")
    return run
