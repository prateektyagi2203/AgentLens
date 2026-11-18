"""Pipeline orchestration: an ordered registry of idempotent steps behind `agentlens run-all`.

M3 plugs in with `register_step("funnel", fn)` (see the contract in `register_step`). Every step runs inside its own
transaction (unless `transactional=False`): a step that raises is rolled back, so earlier steps' outputs stay intact and a
half-written table is never visible. Each run is recorded in `runs` with per-step status, timing and counts.
"""

from __future__ import annotations

import importlib
import json
import time
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from . import db
from .identify.engine import identify
from .ingest import ingest_path
from .sessions import sessionize

CANONICAL_ORDER = ("ingest", "identify", "sessionize", "funnel", "diagnose", "impact", "recommend")
OPTIONAL_STEP_MODULES = (
    "agentlens.funnel", "agentlens.diagnosis", "agentlens.impact", "agentlens.recommend",
)  # fmt: skip


@dataclass
class RunContext:
    """Passed to every step. `params` carries CLI/API options (source, fmt, ...)."""

    run_id: str
    params: dict[str, Any] = field(default_factory=dict)


StepFn = Callable[[duckdb.DuckDBPyConnection, RunContext], dict[str, Any] | None]


@dataclass
class Step:
    name: str
    fn: StepFn
    transactional: bool = True


_REGISTRY: dict[str, Step] = {}


def register_step(name: str, fn: StepFn, *, transactional: bool = True, replace: bool = False) -> None:
    """Register a pipeline step.

    Contract: `fn(con, ctx) -> dict | None`. `con` is the shared DuckDB connection (already inside a transaction when
    `transactional`); `ctx.run_id` / `ctx.params` describe the run. The returned dict (ints/strs) is stored as the step's
    counts in `runs.steps_json`. The step must be idempotent (recompute from its inputs) and may raise to fail the run.
    Execution order follows CANONICAL_ORDER (ingest, identify, sessionize, funnel, diagnose, impact, recommend); names not
    in that list run after it, in registration order. Registering an existing name needs `replace=True`.
    """
    if name in _REGISTRY and not replace:
        raise ValueError(f"step {name!r} already registered (pass replace=True)")
    _REGISTRY[name] = Step(name, fn, transactional)


def unregister_step(name: str) -> None:
    _REGISTRY.pop(name, None)


def _ingest_step(con: duckdb.DuckDBPyConnection, ctx: RunContext) -> dict[str, Any]:
    res = ingest_path(con, ctx.params.get("source"), ctx.params.get("fmt", "jsonl"))
    return res.as_counts()


def _register_builtin() -> None:
    register_step("ingest", _ingest_step, transactional=False, replace=True)  # commits per block with its offset
    register_step("identify", identify, replace=True)
    register_step("sessionize", sessionize, replace=True)


def load_optional_steps() -> list[str]:
    """Import M3 packages if present; each registers its steps at import time."""
    loaded = []
    for mod in OPTIONAL_STEP_MODULES:
        try:
            importlib.import_module(mod)
            loaded.append(mod)
        except ModuleNotFoundError as exc:
            if exc.name != mod:  # a missing dependency inside an existing module is a real error
                raise
    return loaded


def ordered_steps() -> list[Step]:
    rank = {n: i for i, n in enumerate(CANONICAL_ORDER)}
    order = {n: i for i, n in enumerate(_REGISTRY)}
    names = sorted(_REGISTRY, key=lambda n: (rank.get(n, len(rank)), order[n]))
    return [_REGISTRY[n] for n in names]


@dataclass
class RunResult:
    run_id: str
    status: str
    steps: list[dict[str, Any]]

    @property
    def ok(self) -> bool:
        return self.status == "success"


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def run_steps(
    con: duckdb.DuckDBPyConnection, names: list[str] | None = None, params: dict[str, Any] | None = None
) -> RunResult:
    """Run the named steps (default: all, in canonical order). Stops at the first failure."""
    _register_builtin_if_needed()
    load_optional_steps()
    steps = ordered_steps()
    if names is not None:
        unknown = [n for n in names if n not in _REGISTRY]
        if unknown:
            raise KeyError(f"unknown step(s): {unknown}; registered: {list(_REGISTRY)}")
        steps = [s for s in steps if s.name in names]
    ctx = RunContext(run_id=uuid.uuid4().hex[:12], params=params or {})
    started = _now()
    con.execute(
        "INSERT INTO runs (run_id, started_at, steps_json, status, counts_json) VALUES (?, ?, '[]', 'running', '{}')",
        [ctx.run_id, started],
    )
    log: list[dict[str, Any]] = []
    status = "success"
    totals: dict[str, Any] = {}
    for step in steps:
        t0 = time.perf_counter()
        entry: dict[str, Any] = {"name": step.name, "status": "running"}
        try:
            if step.transactional:
                con.execute("BEGIN")
            try:
                counts = step.fn(con, ctx) or {}
                if step.transactional:
                    con.execute("COMMIT")
            except BaseException:
                if step.transactional:
                    con.execute("ROLLBACK")
                raise
            entry.update(status="success", counts=counts)
            totals[step.name] = counts
        except Exception as exc:
            entry.update(status="failed", error=f"{type(exc).__name__}: {exc}", trace=traceback.format_exc(limit=6))
            status = "failed"
        entry["seconds"] = round(time.perf_counter() - t0, 3)
        log.append(entry)
        con.execute(
            "UPDATE runs SET steps_json = ?, counts_json = ? WHERE run_id = ?",
            [json.dumps(log, default=str), json.dumps(totals, default=str), ctx.run_id],
        )
        if status == "failed":
            break
    con.execute("UPDATE runs SET status = ?, finished_at = ? WHERE run_id = ?", [status, _now(), ctx.run_id])
    return RunResult(ctx.run_id, status, log)


def _register_builtin_if_needed() -> None:
    if "identify" not in _REGISTRY:
        _register_builtin()


def run_all(
    con: duckdb.DuckDBPyConnection | None = None, *, source: str | Path | None = None, fmt: str = "jsonl",
    steps: list[str] | None = None,
) -> RunResult:  # fmt: skip
    own = con is None
    conn = con or db.connect()
    try:
        return run_steps(conn, steps, {"source": str(source) if source else None, "fmt": fmt})
    finally:
        if own:
            conn.close()
