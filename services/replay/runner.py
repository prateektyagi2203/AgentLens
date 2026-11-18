"""Select blockers to replay, run the replays, persist them into the `replays` table (steps_json shape: see model.py)."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import duckdb

from .agent import AUTO, new_replay_id, run_replay
from .browser_agent import chromium_available
from .config import HostNotAllowed, ReplayConfig
from .hypotheses import BROWSER_ONLY, HYPOTHESES
from .model import INCONCLUSIVE, ReplayResult, api_verdict

OnStep = Callable[[str, str, str | None], None]
_LOCK = threading.Lock()  # one replay run at a time: never double the load on the target site
HINT_BLOCKERS = {"B15", "B08"}


def top_blockers(con: duckdb.DuckDBPyConnection, n: int) -> list[str]:
    rows = con.execute(
        "SELECT blocker_id FROM impact WHERE blocker_id IS NOT NULL AND blocker_id <> 'B99' "
        "GROUP BY blocker_id ORDER BY SUM(risk_base) DESC, blocker_id LIMIT ?", [n]
    ).fetchall()  # fmt: skip
    if not rows:
        rows = con.execute(
            "SELECT terminal_blocker_id FROM sessions WHERE terminal_blocker_id IS NOT NULL AND terminal_blocker_id <> 'B99' "
            "GROUP BY 1 ORDER BY COUNT(*) DESC, 1 LIMIT ?", [n]
        ).fetchall()  # fmt: skip
    return [r[0] for r in rows if r[0] in HYPOTHESES]


def source_sessions(con: duckdb.DuckDBPyConnection, blocker_id: str, limit: int) -> list[str]:
    rows = con.execute(
        "SELECT session_id FROM sessions WHERE terminal_blocker_id = ? ORDER BY start_ts DESC LIMIT ?", [blocker_id, limit]
    ).fetchall()  # fmt: skip
    return [r[0] for r in rows]


def product_hints(con: duckdb.DuckDBPyConnection, session_ids: list[str], limit: int = 3) -> tuple[str, ...]:
    if not session_ids:
        return ()
    marks = ",".join("?" for _ in session_ids)
    rows = con.execute(
        f"SELECT DISTINCT path FROM requests WHERE session_id IN ({marks}) AND path LIKE '/p/%' LIMIT ?",  # noqa: S608
        [*session_ids, limit],
    ).fetchall()  # fmt: skip
    return tuple(r[0].removeprefix("/p/") for r in rows)


def save(con: duckdb.DuckDBPyConnection, r: ReplayResult, status: str) -> None:
    con.execute(
        """INSERT INTO replays (replay_id, blocker_id, source_session_id, mode, status, started_at, finished_at, steps_json,
                                evidence_dir, verdict_explanation)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (replay_id) DO UPDATE SET status = excluded.status, finished_at = excluded.finished_at,
             steps_json = excluded.steps_json, evidence_dir = excluded.evidence_dir,
             verdict_explanation = excluded.verdict_explanation, mode = excluded.mode""",
        [r.replay_id, r.blocker_id, r.source_session_id, r.mode, status, _naive(r.started_at), _naive(r.finished_at),
         json.dumps(r.steps_payload(), default=str), r.evidence_dir, r.explanation],
    )  # fmt: skip


def _naive(ts: datetime) -> datetime:
    return ts.replace(tzinfo=None)


def choose_mode(blocker_id: str | None, requested: str | None, cfg: ReplayConfig) -> tuple[str, str | None]:
    """Explicit `--mode` always wins. Otherwise browser-only hypotheses (B07) upgrade to browser if Chromium exists."""
    if requested:
        return requested, None
    if blocker_id in BROWSER_ONLY and cfg.auto_browser:
        if chromium_available():
            return "browser", None
        return "fetch", f"{blocker_id} needs a real browser but Chromium is not installed; falling back to fetch mode"
    return cfg.default_mode, None


def replay_blocker(
    con: duckdb.DuckDBPyConnection | None, blocker_id: str | None, cfg: ReplayConfig, *, base_url: str | None = None,
    task: str | None = None, mode: str | None = None, pause_s: float | None = None, sign: bool | None = None,
    vision: bool | None = None, root: Any = None, llm: Any = AUTO, source_session_id: str | None = None,
    hints: tuple[str, ...] = (),
) -> ReplayResult:  # fmt: skip
    """Run and persist one replay. Raises HostNotAllowed (after recording a failed replay) if the host is refused."""
    use_mode, note = choose_mode(blocker_id, mode, cfg)
    kwargs: dict[str, Any] = {
        "base_url": base_url, "task": task, "blocker_id": blocker_id, "root": root, "llm": llm, "pause_s": pause_s,
        "sign": sign, "product_hints": hints, "source_session_id": source_session_id, "vision": vision,
    }  # fmt: skip
    with _LOCK:
        try:
            result = run_replay(cfg, mode=use_mode, **kwargs)
        except HostNotAllowed:
            raise
        except Exception as exc:  # noqa: BLE001 - browser launch problems must not lose the replay
            if use_mode != "browser":
                raise
            result = run_replay(cfg, mode="fetch", **kwargs)
            result.notes.append(f"browser mode failed ({type(exc).__name__}: {exc}); replayed in fetch mode instead")
    if note:
        result.notes.append(note)
    if con is not None:
        save(con, result, "completed")
    return result


def run_replays(
    con: duckdb.DuckDBPyConnection, *, blocker_id: str | None = None, top_n: int | None = None, on_step: OnStep | None = None,
    base_url: str | None = None, task: str | None = None, mode: str | None = None, pause_s: float | None = None,
    sign: bool | None = None, vision: bool | None = None, cfg: ReplayConfig | None = None, root: Any = None, llm: Any = AUTO,
) -> dict[str, int]:  # fmt: skip
    """Replay one blocker (`blocker_id`) or the top-N by risk (`top_n`, default replay.yaml `top_n_blockers`).

    `on_step(name, status, message)` reports progress for the steps `select`, `replay` and `verdict`. Returns counts:
    replays, confirmed, not_confirmed, inconclusive, failed.
    """

    def emit(name: str, status: str, msg: str | None = None) -> None:
        if on_step:
            on_step(name, status, msg)

    cfg = cfg or ReplayConfig.load()
    counts = {"replays": 0, "confirmed": 0, "not_confirmed": 0, "inconclusive": 0, "failed": 0}
    emit("select", "running", None)
    try:
        targets = [blocker_id] if blocker_id else top_blockers(con, top_n or cfg.top_n_blockers)
        targets = targets[: cfg.max_replays_per_run]
    except Exception as exc:  # noqa: BLE001
        emit("select", "failed", str(exc))
        raise
    emit("select", "succeeded", f"{len(targets)} blocker(s): {', '.join(targets) or 'none'}")
    emit("replay", "running", None)
    results: list[ReplayResult] = []
    for bid in targets:
        sessions = source_sessions(con, bid, cfg.sessions_per_blocker)
        hints = product_hints(con, sessions) if bid in HINT_BLOCKERS else ()
        try:
            res = replay_blocker(con, bid, cfg, base_url=base_url, task=task, mode=mode, pause_s=pause_s, sign=sign,
                                 vision=vision, root=root, llm=llm, source_session_id=sessions[0] if sessions else None,
                                 hints=hints)  # fmt: skip
        except Exception as exc:  # noqa: BLE001 - one failing replay must not abort the batch
            counts["failed"] += 1
            _save_failed(con, bid, mode or cfg.default_mode, exc, sessions[0] if sessions else None)
            emit("replay", "running", f"{bid} failed: {exc}")
            continue
        counts["replays"] += 1
        key = api_verdict(res.verdict) or INCONCLUSIVE
        counts[key if key in counts else "inconclusive"] += 1
        results.append(res)
        emit("replay", "running", f"{bid}: {res.verdict}")
    emit("replay", "succeeded" if not counts["failed"] or counts["replays"] else "failed",
         f"{counts['replays']} replayed, {counts['failed']} failed")  # fmt: skip
    emit("verdict", "succeeded", ", ".join(f"{r.blocker_id}={r.verdict}" for r in results) or "no replays")
    return counts


def _save_failed(con: duckdb.DuckDBPyConnection, bid: str | None, mode: str, exc: Exception, session_id: str | None) -> None:
    now = datetime.now(UTC)
    r = ReplayResult(replay_id=new_replay_id(), blocker_id=bid, mode=mode, verdict=INCONCLUSIVE,
                     explanation=f"Replay refused or failed: {type(exc).__name__}: {exc}", started_at=now, finished_at=now,
                     source_session_id=session_id, user_agent=ReplayConfig.load().user_agent)  # fmt: skip
    save(con, r, "failed")

