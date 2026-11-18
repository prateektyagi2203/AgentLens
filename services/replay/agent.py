"""Run one replay end to end and return a `ReplayResult` (no database access here)."""

from __future__ import annotations

import dataclasses
import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from agentlens import settings

from .client import ReplayClient
from .config import ReplayConfig
from .journey import Journey
from .llm import ReplayLLM
from .model import INCONCLUSIVE, ReplayResult
from .planner import make_planner
from .task import parse_task

AUTO: Any = object()


def new_replay_id() -> str:
    return "rp_" + uuid.uuid4().hex[:10]


def run_user_agent(base: str, replay_id: str) -> str:
    """Tag the declared UA with the replay id: still `AgentLens-Replay/...`, but each run is a distinct, traceable client."""
    return f"{base[:-1]}; run={replay_id})" if base.endswith(")") else f"{base} (run={replay_id})"


def evidence_root() -> Path:
    return settings.data_dir() / "replays"


def run_replay(
    cfg: ReplayConfig, *, base_url: str | None = None, task: str | None = None, blocker_id: str | None = None,
    mode: str = "fetch", replay_id: str | None = None, root: Path | None = None, llm: ReplayLLM | None | Any = AUTO,
    transport: httpx.BaseTransport | None = None, pause_s: float | None = None, sign: bool | None = None,
    product_hints: tuple[str, ...] = (), source_session_id: str | None = None, vision: bool | None = None,
) -> ReplayResult:  # fmt: skip
    """Raises `HostNotAllowed` (a PermissionError) before any request if `base_url` is not in the allow-list."""
    replay_id = replay_id or new_replay_id()
    cfg = dataclasses.replace(cfg, user_agent=run_user_agent(cfg.user_agent, replay_id))
    spec = parse_task(task or cfg.default_task)
    started = datetime.now(UTC)
    ev_dir = (root or evidence_root()) / replay_id
    llm_obj = ReplayLLM.from_env() if llm is AUTO else llm
    planner = make_planner(llm_obj, cfg.max_tokens)
    deadline = time.monotonic() + cfg.max_seconds
    client = ReplayClient(cfg, base_url, transport=transport, pause_s=pause_s, sign=sign, max_requests=cfg.max_steps * 4,
                          deadline=deadline)  # fmt: skip
    ev_dir.mkdir(parents=True, exist_ok=True)
    try:
        if mode == "browser":
            from .browser_agent import BrowserJourney

            use_vision = cfg.vision if vision is None else vision
            journey: Journey = BrowserJourney(cfg, client, spec, target=blocker_id, planner=planner, evidence_dir=ev_dir,
                                              product_hints=product_hints, vision_llm=llm_obj if use_vision else None)  # fmt: skip
        else:
            journey = Journey(cfg, client, spec, target=blocker_id, planner=planner, evidence_dir=ev_dir,
                              product_hints=product_hints)  # fmt: skip
        try:
            journey.run()
        finally:
            journey.close()
        verdict, explanation = journey.outcome()
        notes = list(journey.notes)
        fallback = getattr(planner, "fallback_reason", None)
        if fallback:
            notes.append(f"OpenAI planner fell back to the deterministic planner: {fallback}")
        net = list(client.network_log) + list(getattr(journey, "browser_network", []))
        net.sort(key=lambda e: e["ts"])
        result = ReplayResult(
            replay_id=replay_id, blocker_id=blocker_id, mode=mode, verdict=verdict if verdict else INCONCLUSIVE,
            explanation=explanation, started_at=started, finished_at=datetime.now(UTC), steps=journey.steps,
            network_log=net, signals=journey.signals, task=spec.text, task_completed=journey.ordered,
            order_id=journey.order_id, workarounds=journey.workarounds, user_agent=cfg.user_agent,
            signed_requests=client.signed, evidence_dir=str(ev_dir), source_session_id=source_session_id,
            planner=planner.name, llm_tokens=planner.tokens_used + int(getattr(journey, "vision_tokens", 0)), notes=notes,
        )  # fmt: skip
    finally:
        client.close()
    (ev_dir / "evidence.json").write_text(
        json.dumps({"replay_id": replay_id, "verdict": result.verdict, "explanation": result.explanation,
                    "signals": [s.__dict__ for s in result.signals], "workarounds": result.workarounds,
                    "notes": result.notes}, indent=2, default=str),  # fmt: skip
        encoding="utf-8",
    )
    return result
