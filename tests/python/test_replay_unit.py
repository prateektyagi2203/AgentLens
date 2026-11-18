"""Replay agent unit tests: safety rules (allow-list, robots, budgets), planning fallbacks and persistence. No store needed."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from agentlens import db
from agentlens.replay import runner
from agentlens.replay.agent import run_replay, run_user_agent
from agentlens.replay.client import BudgetExceeded, ReplayClient
from agentlens.replay.config import AllowList, HostNotAllowed, ReplayConfig, RobotsDisallowed
from agentlens.replay.llm import ReplayLLM
from agentlens.replay.model import CONFIRMED, NOT_REPRODUCED, ReplayResult, Signal, StepRecord
from agentlens.replay.planner import DeterministicPlanner, OpenAIPlanner, make_planner
from agentlens.replay.task import parse_task

BASE = "http://localhost:3100"


def cfg(**kw: Any) -> ReplayConfig:
    c = ReplayConfig(allowed_hosts=["localhost:3100", "127.0.0.1:3100"], step_pause_s=0.0)
    for k, v in kw.items():
        setattr(c, k, v)
    return c


class Recorder:
    """httpx transport that records requests and serves a tiny site plus robots.txt."""

    def __init__(self, robots: str = "User-agent: *\nAllow: /\n", redirect_to: str | None = None) -> None:
        self.seen: list[httpx.Request] = []
        self.robots = robots
        self.redirect_to = redirect_to

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=self.robots)
        if request.url.path == "/hop" and self.redirect_to:
            return httpx.Response(302, headers={"location": self.redirect_to})
        return httpx.Response(200, text="<html>ok</html>")

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


# ---- allow-list -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("http://localhost:3100/p/x", True),
        ("http://127.0.0.1:3100/", True),
        ("http://localhost:3101/", False),
        ("http://example.com/", False),
        ("http://localhost:3100@evil.test/", False),
        ("http://evil.test/?u=localhost:3100", False),
        ("ftp://localhost:3100/", False),
        ("http://user:pw@localhost:3100/", False),
    ],
)
def test_allow_list(url: str, ok: bool) -> None:
    assert AllowList(("localhost:3100", "127.0.0.1:3100")).allows(url) is ok


def test_allow_list_entry_without_port_means_default_ports() -> None:
    al = AllowList(("shop.example",))
    assert al.allows("https://shop.example/x") and al.allows("http://shop.example/x")
    assert not al.allows("https://shop.example:8443/x")


def test_client_refuses_disallowed_host_before_any_request() -> None:
    rec = Recorder()
    with pytest.raises(HostNotAllowed):
        ReplayClient(cfg(), "http://example.com", transport=rec.transport)
    with ReplayClient(cfg(), BASE, transport=rec.transport) as c, pytest.raises(HostNotAllowed):
        c.request("GET", "http://example.com/steal")
    assert not [r for r in rec.seen if r.url.host == "example.com"]


def test_redirect_to_disallowed_host_is_not_followed() -> None:
    rec = Recorder(redirect_to="http://example.com/landing")
    with ReplayClient(cfg(), BASE, transport=rec.transport) as c, pytest.raises(HostNotAllowed):
        c.request("GET", "/hop")
    assert all(r.url.host != "example.com" for r in rec.seen)


def test_run_replay_refuses_non_allowed_base_url_without_traffic(tmp_path: Path) -> None:
    rec = Recorder()
    with pytest.raises(HostNotAllowed):
        run_replay(cfg(), base_url="http://example.com", transport=rec.transport, root=tmp_path, llm=None)
    assert rec.seen == []


# ---- robots, identity, budgets ----------------------------------------------------------------------------------


def test_robots_disallow_is_respected_and_can_be_observed() -> None:
    rec = Recorder(robots="User-agent: AgentLens-Replay\nDisallow: /cart\n")
    with ReplayClient(cfg(), BASE, transport=rec.transport) as c:
        assert c.request("GET", "/p/shirt").status == 200
        assert c.robots_allows("/cart") is False
        with pytest.raises(RobotsDisallowed):
            c.request("GET", "/cart")
    assert not [r for r in rec.seen if r.url.path == "/cart"]


def test_requests_carry_the_replay_user_agent() -> None:
    rec = Recorder()
    with ReplayClient(cfg(), BASE, transport=rec.transport) as c:
        c.request("GET", "/")
    assert all("AgentLens-Replay" in r.headers["user-agent"] for r in rec.seen)
    assert all("signature" not in r.headers for r in rec.seen)


def test_signed_variant_adds_web_bot_auth_headers() -> None:
    rec = Recorder()
    with ReplayClient(cfg(), BASE, transport=rec.transport, sign=True) as c:
        c.request("GET", "/", check_robots=False)
    h = rec.seen[0].headers
    assert "signature" in h and "signature-input" in h and "signature-agent" in h


def test_request_budget_is_a_hard_stop() -> None:
    rec = Recorder()
    with ReplayClient(cfg(), BASE, transport=rec.transport, max_requests=2) as c:
        c.request("GET", "/", check_robots=False)
        c.request("GET", "/a", check_robots=False)
        with pytest.raises(BudgetExceeded):
            c.request("GET", "/b", check_robots=False)


def test_pacing_sleeps_between_requests() -> None:
    sleeps: list[float] = []
    rec = Recorder()
    with ReplayClient(cfg(), BASE, transport=rec.transport, pause_s=2.0, sleep=sleeps.append) as c:
        c.request("GET", "/", check_robots=False)
        c.request("GET", "/a", check_robots=False)
    assert len(sleeps) == 1 and 1.0 < sleeps[0] <= 2.0


def test_run_user_agent_is_unique_but_still_exempt_token() -> None:
    a = run_user_agent("AgentLens-Replay/1.0 (+https://x)", "rp_1")
    b = run_user_agent("AgentLens-Replay/1.0 (+https://x)", "rp_2")
    assert a != b and a.startswith("AgentLens-Replay/1.0") and "run=rp_1" in a


# ---- task parsing and planning ----------------------------------------------------------------------------------


def test_parse_default_task() -> None:
    t = parse_task("buy a size-M blue shirt under 1500 INR, deliver to pincode 560001")
    assert (t.size, t.colour, t.category, t.max_price, t.pincode) == ("M", "blue", "shirt", 1500, "560001")
    assert t.query == "blue shirt"


def _llm(answers: list[dict[str, Any] | str], tokens: int = 50) -> ReplayLLM:
    queue = list(answers)

    def handler(request: httpx.Request) -> httpx.Response:
        a = queue.pop(0)
        content = a if isinstance(a, str) else json.dumps(a)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {"total_tokens": tokens}})

    return ReplayLLM("sk-test", "gpt-test", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_deterministic_planner_takes_first_allowed() -> None:
    assert DeterministicPlanner().decide("g", {}, ["search", "open_pdp"]).action == "search"
    assert make_planner(None, 1000).name == "deterministic"


def test_openai_planner_picks_valid_action_and_falls_back_on_invalid() -> None:
    p = OpenAIPlanner(_llm([{"action": "open_pdp", "reason": "pdp first"}, {"action": "rm -rf /"}]), max_tokens=1000)
    assert p.decide("g", {}, ["search", "open_pdp"]).action == "open_pdp"
    d = p.decide("g", {}, ["search", "open_pdp"])
    assert d.action == "search" and p.fallback_reason
    assert p.decide("g", {}, ["x", "y"]).action == "x"  # stays on the deterministic path after a bad answer


def test_openai_planner_stops_calling_the_model_at_the_token_budget() -> None:
    llm = _llm([{"action": "b"}, {"action": "b"}], tokens=600)
    p = OpenAIPlanner(llm, max_tokens=1000)
    p.decide("g", {}, ["a", "b"])
    p.decide("g", {}, ["a", "b"])
    assert llm.tokens_used == 1200
    assert p.decide("g", {}, ["a", "b"]).action == "a"
    assert llm.calls == 2 and "token budget" in (p.fallback_reason or "")


def test_openai_planner_falls_back_when_the_api_errors() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    llm = ReplayLLM("sk-test", "m", client=httpx.Client(transport=httpx.MockTransport(boom)))
    assert OpenAIPlanner(llm, max_tokens=1000).decide("g", {}, ["a", "b"]).action == "a"


def test_llm_prompts_do_not_carry_pii() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.content.decode())
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"action": "a"}'}}], "usage": {}})

    llm = ReplayLLM("k", "m", client=httpx.Client(transport=httpx.MockTransport(handler)))
    OpenAIPlanner(llm, max_tokens=1000).decide("find shirt", {"email": "real.person@gmail.com", "phone": "+919812345678"}, ["a", "b"])
    assert "real.person@gmail.com" not in seen[0] and "9812345678" not in seen[0]


# ---- persistence and the runner ---------------------------------------------------------------------------------


def _result(bid: str, verdict: str, rid: str) -> ReplayResult:
    now = datetime.now(UTC)
    return ReplayResult(
        replay_id=rid, blocker_id=bid, mode="fetch", verdict=verdict, explanation=f"{bid} {verdict}", started_at=now,
        finished_at=now, user_agent="AgentLens-Replay/1.0", task="t",
        steps=[StepRecord(1, "add_to_cart", "POST", "/api/cart", 409, 12, "409 PINCODE_REQUIRED", "step_1.png", bid, {"code": "x"})],
        signals=[Signal(bid, verdict == CONFIRMED, "d", 1)],
    )  # fmt: skip


@pytest.fixture
def writable_db(tmp_path: Path):  # type: ignore[no-untyped-def]
    con = db.connect(tmp_path / "t.duckdb")
    yield con
    con.close()


def test_run_replays_persists_contract_shape_and_reports_steps(writable_db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_replay(c: ReplayConfig, **kw: Any) -> ReplayResult:
        bid = kw["blocker_id"]
        return _result(bid, CONFIRMED if bid == "B05" else NOT_REPRODUCED, f"rp_{bid}")

    monkeypatch.setattr(runner, "run_replay", fake_run_replay)
    events: list[tuple[str, str, str | None]] = []
    counts = runner.run_replays(writable_db, blocker_id="B05", cfg=cfg(), on_step=lambda *a: events.append(a))
    assert counts == {"replays": 1, "confirmed": 1, "not_confirmed": 0, "inconclusive": 0, "failed": 0}
    assert {e[0] for e in events} == {"select", "replay", "verdict"}
    assert ("verdict", "succeeded") == events[-1][:2]
    row = writable_db.execute(
        "SELECT blocker_id, mode, status, steps_json, verdict_explanation FROM replays WHERE replay_id = 'rp_B05'"
    ).fetchone()
    assert row[:3] == ("B05", "fetch", "completed") and "B05" in row[4]
    body = json.loads(row[3])
    assert body["verdict"] == "confirmed" and body["signed_requests"] is False and "AgentLens-Replay" in body["user_agent"]
    step = body["steps"][0]
    assert step["screenshot_url"] == "/api/replays/rp_B05/screenshots/step_1.png" and step["blocker_id"] == "B05"
    assert isinstance(body["network_log"], list)


def test_not_reproduced_is_stored_as_not_confirmed(writable_db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "run_replay", lambda c, **kw: _result("B10", NOT_REPRODUCED, "rp_b10"))
    counts = runner.run_replays(writable_db, blocker_id="B10", cfg=cfg())
    assert counts["not_confirmed"] == 1
    body = writable_db.execute("SELECT steps_json FROM replays WHERE replay_id = 'rp_b10'").fetchone()[0]
    assert json.loads(body)["verdict"] == "not_confirmed"


def test_refused_host_is_recorded_as_failed_not_raised_from_the_batch(writable_db: Any) -> None:
    counts = runner.run_replays(writable_db, blocker_id="B05", cfg=cfg(), base_url="http://example.com")
    assert counts["failed"] == 1 and counts["replays"] == 0
    row = writable_db.execute("SELECT status, verdict_explanation FROM replays").fetchone()
    assert row[0] == "failed" and "allow-list" in row[1]


def test_top_blockers_follow_ranked_risk(chain_db: Any) -> None:
    top = runner.top_blockers(chain_db, 3)
    assert 1 <= len(top) <= 3 and "B99" not in top
