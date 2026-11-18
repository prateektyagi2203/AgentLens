"""Synthetic traffic: determinism, store simulation per toggle, ground truth, live driver over a mock transport."""

from __future__ import annotations

import json
import random

import httpx
import pytest
from agentlens.synth import offline
from agentlens.synth.catalog import Catalog
from agentlens.synth.config import FRICTION_IDS, SynthConfig
from agentlens.synth.live import parse_rate, run_live
from agentlens.synth.model import API, ASSET, PAGE, Req
from agentlens.synth.personas import make_client
from agentlens.synth.site import SiteSim

CFG = SynthConfig.load()
CAT = Catalog.load()


def gen(out, sessions=300, days=2, seed=7, **kw):
    return offline.run_offline(sessions=sessions, days=days, seed=seed, out=out / "logs", run_id=f"t{seed}", **kw)


def lines(out):
    rows = []
    for f in sorted((out / "logs").glob("access-*.jsonl")):
        rows += [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines()]
    return rows


def test_same_seed_is_byte_identical_and_other_seed_differs(tmp_path):
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    gen(a)
    gen(b)
    gen(c, seed=8)
    names = sorted(p.name for p in (a / "logs").glob("*.jsonl"))
    assert names and names == sorted(p.name for p in (b / "logs").glob("*.jsonl"))
    for n in names:
        assert (a / "logs" / n).read_bytes() == (b / "logs" / n).read_bytes()
    assert (a / "orders.jsonl").read_bytes() == (b / "orders.jsonl").read_bytes()
    assert (a / "ground_truth" / "gt-t7.jsonl").read_bytes() == (b / "ground_truth" / "gt-t7.jsonl").read_bytes()
    assert lines(a) != lines(c)


def test_refuses_to_overwrite_without_force(tmp_path):
    gen(tmp_path)
    with pytest.raises(FileExistsError):
        gen(tmp_path)
    gen(tmp_path, force=True)


def test_records_follow_the_log_contract_and_persona_mix(tmp_path):
    res = gen(tmp_path, sessions=600)
    rows = lines(tmp_path)
    assert res.lines == len(rows) and len({r["request_id"] for r in rows}) == len(rows)
    must = {"ts", "request_id", "method", "host", "path", "query", "status", "ip_hash", "user_agent", "event_type", "meta"}
    assert all(must <= r.keys() for r in rows[:500])
    assert {r["event_type"] for r in rows} <= {"request", "beacon", "order", "config_change"}
    assert all(r["meta"].get("synth_session_id") for r in rows if r["event_type"] != "config_change")
    shares = res.persona_counts
    assert shares["human"] / 600 == pytest.approx(0.70, abs=0.06)
    assert {"signed_agent", "chatgpt_fetcher", "claude_fetcher", "forged_signature_bot"} <= set(shares)
    gt = [json.loads(x) for x in (tmp_path / "ground_truth" / "gt-t7.jsonl").read_text().splitlines()]
    assert len(gt) == 600
    need = {"run_id", "synthetic_session_id", "persona", "expected_tier", "operator", "agent_class", "task",
            "toggles_active", "blocker_hit", "stage_of_failure", "converted"}  # fmt: skip
    assert need <= gt[0].keys()
    assert {g["expected_tier"] for g in gt} == {"human", "verified", "declared", "suspected"}
    ua_tokens = ("ChatGPT-User", "ClaudeBot", "Claude-User", "Perplexity-User", "TestSignedAgent", "Googlebot")
    human_sessions = {g["synthetic_session_id"] for g in gt if g["persona"] == "human"}
    assert not any(any(t in r["user_agent"] for t in ua_tokens) for r in rows
                   if r["meta"].get("synth_session_id") in human_sessions and r.get("user_agent"))  # fmt: skip


def test_before_state_has_friction_errors_after_state_removes_them(tmp_path):
    gen(tmp_path / "b", sessions=800, state="before")
    gen(tmp_path / "a", sessions=800, state="after")

    def codes(out):
        return {r["meta"].get("error_code") for r in lines(out) if r["event_type"] == "request"}

    before, after = codes(tmp_path / "b"), codes(tmp_path / "a")
    assert {"PINCODE_REQUIRED", "AUTH_REQUIRED"} <= before
    assert not ({"PINCODE_REQUIRED", "AUTH_REQUIRED"} & after)


def test_before_after_scenario_writes_config_change_and_flips_behaviour(tmp_path):
    res = gen(tmp_path, sessions=1200, days=4, switch_after_days=2)
    rows = lines(tmp_path)
    changes = [r for r in rows if r["event_type"] == "config_change"]
    assert len(changes) == 1 and "F05" in changes[0]["meta"]["changed"]
    switch = changes[0]["ts"]
    gated = [r for r in rows if r["meta"].get("error_code") in ("PINCODE_REQUIRED", "AUTH_REQUIRED")]
    assert gated and all(r["ts"] <= switch for r in gated)
    assert res.sessions == 1200


def _client(persona, seed=1):
    return make_client(persona, CFG.personas[persona], random.Random(seed), f"syn-test-{persona}")


def _site(**on):
    toggles = {f: False for f in FRICTION_IDS} | on
    return SiteSim(CFG, CAT, lambda _ts: toggles)



def test_f01_bot_wall_blocks_agent_uas_not_browsers_or_assets():
    site = _site(F01=True)
    page = Req("GET", "/", kind=PAGE)
    assert site.respond(_client("chatgpt_fetcher"), page, 0).error_code == "BOT_CHALLENGE"
    assert site.respond(_client("signed_agent"), page, 0).status == 403
    assert site.respond(_client("human"), page, 0).status in (200, 500)
    assert site.respond(_client("chatgpt_fetcher"), Req("GET", "/img/x.png", kind=ASSET), 0).status == 200
    assert _site().respond(_client("chatgpt_fetcher", 2), page, 0).status in (200, 500)


def test_f12_rate_limit_returns_429_after_20_requests_per_minute():
    site, c = _site(F12=True), _client("chatgpt_fetcher")
    statuses = [site.respond(c, Req("GET", f"/c/x{i}", kind=PAGE), float(i)).status for i in range(25)]
    assert statuses[:20].count(429) == 0 and statuses[20:] == [429] * 5
    again = site.respond(c, Req("GET", "/", kind=PAGE), 200.0)
    assert again.status != 429


def test_f13_slow_pdp_adds_seconds_and_f14_changes_robots():
    c = _client("human")
    slow = _site(F13=True).respond(c, Req("GET", "/p/some-product", kind=PAGE), 0)
    fast = _site().respond(_client("human", 2), Req("GET", "/p/some-product", kind=PAGE), 0)
    assert slow.duration_ms >= 6000 and fast.duration_ms < 6000
    robots = Req("GET", "/robots.txt", kind=PAGE)
    assert _site(F14=True).respond(_client("chatgpt_fetcher"), robots, 0).data["disallow_pdp"] is True
    assert _site().respond(_client("chatgpt_fetcher"), robots, 0).data["disallow_pdp"] is False


def test_f05_f06_cart_guards_in_order():
    p = next(x for x in CAT.products if all(v["stock"] > 0 for v in x["variants"]))
    v = p["variants"][0]
    cart = Req("POST", "/api/cart", kind=API, body={"product_id": p["id"], "size": v["size"], "colour": v["colour"], "qty": 1})
    assert _site(F05=True, F06=True).respond(_client("human"), cart, 0).error_code == "PINCODE_REQUIRED"
    assert _site(F06=True).respond(_client("human", 3), cart, 0).error_code == "AUTH_REQUIRED"
    ok = _site()
    codes = {ok.respond(_client("human", s), cart, 0).status for s in range(6)}
    assert 201 in codes


def test_parse_rate():
    assert parse_rate("20/s") == 20.0 and parse_rate(5) == 5.0 and parse_rate("2.5") == 2.5


@pytest.mark.asyncio
async def test_live_runner_over_mock_transport(tmp_path):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        headers = {"set-cookie": "dt_sid=abc123; Path=/; HttpOnly"}
        if request.url.path.startswith("/api/"):
            return httpx.Response(200, json={"ok": True}, headers=headers)
        return httpx.Response(200, text="<html></html>", headers=headers)

    res = await run_live(sessions=40, rate="5000/s", seed=3, store_url="http://store.test", speed=100000.0,
                         data_dir=tmp_path, run_id="live-t", transport=httpx.MockTransport(handler))  # fmt: skip
    assert res.sessions == 40 and res.requests == len(seen) > 40 and res.errors == 0
    assert all(r.headers.get("x-synth-session", "").startswith("syn-") for r in seen)
    assert all(r.headers.get("x-forwarded-for") for r in seen)
    signed = [r for r in seen if r.headers.get("signature-input")]
    assert signed and all('tag="web-bot-auth"' in r.headers["signature-input"] for r in signed)
    assert all(r.headers["signature-agent"] for r in signed)
    gt = [json.loads(x) for x in (tmp_path / "ground_truth" / "gt-live-t.jsonl").read_text().splitlines()]
    assert len(gt) == 40 and {"persona", "expected_tier", "converted"} <= gt[0].keys()
