"""Replay agent against the real demo store (node) started on a free port. Run with `pytest -m integration`.

One store process serves the whole module; each case sets the friction state through the store's admin API and replays
the default task in fetch mode. Every run uses its own User-Agent suffix, so the store keeps no state between replays.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from agentlens import db
from agentlens.replay.agent import run_replay
from agentlens.replay.browser_agent import chromium_available
from agentlens.replay.config import HostNotAllowed, ReplayConfig
from agentlens.replay.model import CONFIRMED, INCONCLUSIVE, NOT_REPRODUCED, ReplayResult
from agentlens.replay.runner import replay_blocker, run_replays
from store_harness import StoreServer

pytestmark = pytest.mark.integration

if shutil.which("node") is None:  # pragma: no cover
    pytest.skip("node is not installed", allow_module_level=True)


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Iterator[StoreServer]:
    s = StoreServer(tmp_path_factory.mktemp("store"))
    s.start()
    try:
        yield s
    finally:
        s.stop()


@pytest.fixture
def cfg(store: StoreServer) -> ReplayConfig:
    c = ReplayConfig.load()
    c.allowed_hosts = [*c.allowed_hosts, store.base_url.removeprefix("http://")]
    c.step_pause_s = 0.0
    return c


def replay(store: StoreServer, cfg: ReplayConfig, tmp_path: Path, on: set[str], target: str | None, **kw: Any) -> ReplayResult:
    store.set_friction(on)
    mode = kw.pop("mode", "fetch")
    return run_replay(cfg, base_url=store.base_url, blocker_id=target, mode=mode, root=tmp_path, pause_s=0.0, llm=None, **kw)


def seen(r: ReplayResult, bid: str) -> bool:
    return any(s.blocker_id == bid and s.present for s in r.signals)


# The five hypotheses the spec requires, each with only its own friction on.
@pytest.mark.parametrize(
    ("friction", "blocker"),
    [("F05", "B05"), ("F06", "B06"), ("F10", "B10"), ("F03", "B03"), ("F09", "B09")],
)
def test_required_blockers_are_confirmed(
    store: StoreServer, cfg: ReplayConfig, tmp_path: Path, friction: str, blocker: str
) -> None:
    r = replay(store, cfg, tmp_path, {friction}, blocker)
    assert r.verdict == CONFIRMED, r.explanation
    assert seen(r, blocker)
    assert r.steps and all(s.url for s in r.steps)
    assert "AgentLens-Replay" in r.user_agent and not r.signed_requests
    assert (tmp_path / r.replay_id / "evidence.json").exists()


def test_clean_store_completes_the_task_with_nothing_reproduced(store: StoreServer, cfg: ReplayConfig, tmp_path: Path) -> None:
    r = replay(store, cfg, tmp_path, set(), None)
    assert r.task_completed and r.order_id, r.explanation
    assert r.blockers_observed == [] or r.blockers_observed == ["B08"]  # the first blue shirt is naturally out of stock in M
    assert r.verdict == NOT_REPRODUCED


@pytest.mark.parametrize("blocker", ["B05", "B06", "B10"])
def test_targeting_a_blocker_on_a_clean_store_is_not_reproduced(
    store: StoreServer, cfg: ReplayConfig, tmp_path: Path, blocker: str
) -> None:
    r = replay(store, cfg, tmp_path, set(), blocker)
    assert r.verdict == NOT_REPRODUCED, r.explanation


def test_walls_stack_and_the_agent_finishes_through_test_data(store: StoreServer, cfg: ReplayConfig, tmp_path: Path) -> None:
    r = replay(store, cfg, tmp_path, {"F05", "F06", "F10"}, None)
    assert {"B05", "B06", "B10"} <= set(r.blockers_observed)
    assert r.task_completed and r.workarounds


# Remaining frictions: the matrix the docs promise (F07/F08 are client-side overlays: fetch mode is inconclusive by design).
@pytest.mark.parametrize(
    ("friction", "blocker", "hints"),
    [
        ("F01", "B01", ()), ("F02", "B02", ()), ("F04", "B04", ()), ("F11", "B15", ("navy-kurta-style-shirt",)),
        ("F12", "B12", ()), ("F13", "B13", ()), ("F14", "B14", ()), ("F15", "B11", ()), ("F16", "B08", ()),
    ],
)  # fmt: skip
def test_friction_matrix_confirmed_in_fetch_mode(
    store: StoreServer, cfg: ReplayConfig, tmp_path: Path, friction: str, blocker: str, hints: tuple[str, ...]
) -> None:
    r = replay(store, cfg, tmp_path, {friction}, blocker, product_hints=hints)
    assert r.verdict == CONFIRMED, r.explanation


def test_overlays_need_a_browser_so_fetch_mode_is_inconclusive(store: StoreServer, cfg: ReplayConfig, tmp_path: Path) -> None:
    r = replay(store, cfg, tmp_path, {"F07", "F08"}, "B07")
    assert r.verdict == INCONCLUSIVE


def test_replay_is_signed_when_asked(store: StoreServer, cfg: ReplayConfig, tmp_path: Path) -> None:
    r = replay(store, cfg, tmp_path, set(), None, sign=True)
    assert r.signed_requests and r.task_completed


def test_non_allowed_host_is_refused(store: StoreServer, cfg: ReplayConfig, tmp_path: Path) -> None:
    store.set_friction(set())
    with pytest.raises(HostNotAllowed):
        run_replay(cfg, base_url="http://example.com", mode="fetch", root=tmp_path, llm=None)
    cfg.allowed_hosts = [h for h in cfg.allowed_hosts if h != store.base_url.removeprefix("http://")]
    with pytest.raises(HostNotAllowed):
        run_replay(cfg, base_url=store.base_url, mode="fetch", root=tmp_path, llm=None)


def test_replay_is_stored_in_the_replays_table(store: StoreServer, cfg: ReplayConfig, tmp_path: Path) -> None:
    store.set_friction({"F05"})
    con = db.connect(tmp_path / "t.duckdb")
    try:
        counts = run_replays(con, blocker_id="B05", cfg=cfg, base_url=store.base_url, mode="fetch", pause_s=0.0, root=tmp_path, llm=None)
        assert counts["confirmed"] == 1 and counts["failed"] == 0
        status, mode, expl, ev = con.execute("SELECT status, mode, verdict_explanation, evidence_dir FROM replays").fetchone()
        assert (status, mode) == ("completed", "fetch") and "B05" in expl and Path(ev).exists()
    finally:
        con.close()


@pytest.mark.skipif(not chromium_available(), reason="Playwright Chromium is not installed")
def test_browser_mode_clean_run_and_overlay(store: StoreServer, cfg: ReplayConfig, tmp_path: Path) -> None:
    clean = replay(store, cfg, tmp_path, set(), None, mode="browser")
    assert clean.task_completed, clean.explanation
    assert any(s.screenshot for s in clean.steps)
    assert (tmp_path / clean.replay_id / next(s.screenshot for s in clean.steps if s.screenshot)).exists()
    overlay = replay(store, cfg, tmp_path, {"F07"}, "B07", mode="browser")
    assert overlay.verdict == CONFIRMED, overlay.explanation


def test_blocker_replay_helper_runs_without_a_database(store: StoreServer, cfg: ReplayConfig, tmp_path: Path) -> None:
    store.set_friction({"F06"})
    r = replay_blocker(None, "B06", cfg, base_url=store.base_url, mode="fetch", pause_s=0.0, root=tmp_path, llm=None)
    assert r.verdict == CONFIRMED
