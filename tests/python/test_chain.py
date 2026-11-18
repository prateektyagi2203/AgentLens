"""M3 chain: idempotent `run-all`, rules-only without network, site checks, LLM provider, redaction."""

from __future__ import annotations

import json
import socket
from datetime import datetime

import httpx
import pytest
from agentlens import db, pipeline
from agentlens.diagnosis import engine
from agentlens.diagnosis.llm import (
    MockProvider,
    OpenAIProvider,
    SessionSummary,
    get_provider,
    redact,
    redact_path,
)  # fmt: skip
from agentlens.diagnosis.sitechecks import parse_robots, run_site_checks, site_check_summary
from agentlens.eval.fakestore import store_transport

PARAMS = {"skip_site_probe": True, "llm_provider": "off", "fmt": "jsonl"}

SNAPSHOT_SQL = {
    "sessions": "SELECT session_id, max_stage, terminal_blocker_id, round(blocker_confidence, 4), diagnosis_method FROM sessions ORDER BY 1",
    "stages": "SELECT session_id, stage_id FROM session_stages ORDER BY 1, 2",
    "hits": "SELECT session_id, blocker_id, stage_id, round(confidence, 4), is_terminal, evidence_json FROM blocker_hits ORDER BY 1, 2",
    "funnel": "SELECT segment_type, segment, day, stage_id, sessions_reached FROM funnel_stats ORDER BY 1, 2, 3, 4",
    "impact": "SELECT blocker_id, sessions_blocked, round(risk_base, 2) FROM impact ORDER BY 1",
    "recs": "SELECT rec_id, round(priority_score, 2), body FROM recommendations ORDER BY 1",
}


def snapshot(con):
    return {k: con.execute(q).fetchall() for k, q in SNAPSHOT_SQL.items()}


def test_run_all_is_idempotent(synth_logs):
    con = db.connect(":memory:")
    params = {"source": str(synth_logs), **PARAMS}
    first = pipeline.run_steps(con, None, params)
    assert first.ok and [s["name"] for s in first.steps] == [
        "ingest", "identify", "sessionize", "funnel", "diagnose", "impact", "recommend",
    ]  # fmt: skip
    before = snapshot(con)
    n_requests = con.execute("SELECT count(*) FROM requests").fetchone()[0]
    assert pipeline.run_steps(con, None, params).ok
    assert con.execute("SELECT count(*) FROM requests").fetchone()[0] == n_requests
    assert snapshot(con) == before
    assert before["hits"] and before["impact"] and before["recs"]


def test_chain_rules_only_works_offline(synth_logs, monkeypatch):
    def refuse(*_a, **_k):
        raise OSError("network disabled in this test")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    con = db.connect(":memory:")
    res = pipeline.run_steps(con, None, {"source": str(synth_logs), "fmt": "jsonl", "llm_provider": "off"})
    assert res.ok, res.steps
    diagnose = next(s for s in res.steps if s["name"] == "diagnose")
    assert diagnose["counts"]["llm_provider"] == "off"
    assert con.execute("SELECT count(*) FROM sessions WHERE diagnosis_method = 'llm'").fetchone()[0] == 0


def test_site_probe_offline_degrades_to_skipped(monkeypatch):
    def refuse(*_a, **_k):
        raise OSError("network disabled in this test")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    con = db.connect(":memory:")
    out = run_site_checks(con, "http://store.invalid:3000", timeout_s=1)
    assert out["status"] == "skipped" and "unreachable" in out["reason"]
    assert run_site_checks(con, None)["status"] == "skipped"
    rows = con.execute("SELECT check_name, result FROM site_checks").fetchall()
    assert {r[0] for r in rows} == {"site_probe"} and {r[1] for r in rows} == {"skipped"}
    assert site_check_summary(con) == []  # skipped rows are never presented as a check result


def test_site_checks_read_what_the_store_renders():
    con = db.connect(":memory:")
    out = run_site_checks(con, "http://store.test", transport=store_transport({"F03", "F14", "F09"}), catalog_slugs=["white-sneaker"],
                          now=datetime(2026, 11, 1))  # fmt: skip
    res = out["results"]
    assert out["status"] == "ok"
    assert res["pdp_ssr_price"] == "fail" and res["robots_txt"] == "fail" and res["size_guide_table"] == "fail"
    assert res["pdp_jsonld_product"] == "pass"
    summary = {r["check"]: r for r in site_check_summary(con)}
    assert "chatgpt-user" in summary["robots_txt"]["details"]["blocked_agents"]

    clean = run_site_checks(db.connect(":memory:"), "http://store.test", transport=store_transport(set()), catalog_slugs=["white-sneaker"])
    assert clean["results"]["pdp_ssr_price"] == clean["results"]["robots_txt"] == clean["results"]["size_guide_table"] == "pass"


def test_site_checks_rerun_updates_validity_window():
    con = db.connect(":memory:")
    run_site_checks(con, "http://store.test", transport=store_transport({"F03"}), catalog_slugs=["a"], now=datetime(2026, 11, 1))
    run_site_checks(con, "http://store.test", transport=store_transport(set()), catalog_slugs=["a"], now=datetime(2026, 11, 8))
    latest = {r["check"]: r["result"] for r in site_check_summary(con)}
    assert latest["pdp_ssr_price"] == "pass"
    assert con.execute("SELECT count(DISTINCT run_ts) FROM site_checks").fetchone()[0] == 2


def test_parse_robots():
    text = "User-agent: *\nAllow: /\n\nUser-agent: GPTBot\nUser-agent: ChatGPT-User\nDisallow: /p/\n\nUser-agent: ClaudeBot\nDisallow: /admin"
    assert parse_robots(text) == ["chatgpt-user", "gptbot"]
    assert parse_robots("User-agent: *\nDisallow: /") == []  # wildcard blocks are not an AI-agent-specific finding


def test_redaction_removes_pii():
    assert redact("mail a.b@example.com or call +91 98765 43210, order /orders/0123456789abcdef/x") == (
        "mail {email} or call {phone}, order /orders/{id}/x"
    )
    assert redact_path("/api/orders?email=a@b.co&phone=9876543210") == "/api/orders"
    summary = SessionSummary("s1", "user_fetcher", "S2", [
        {"method": "GET", "path": redact_path("/p/x?email=a@b.co"), "status": 200, "error_code": None, "duration_ms": 10},
    ])  # fmt: skip
    assert "a@b.co" not in summary.prompt()


def test_mock_provider_is_deterministic_and_default(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AGENTLENS_LLM_PROVIDER", raising=False)
    assert isinstance(get_provider(), MockProvider)
    monkeypatch.setenv("AGENTLENS_LLM_PROVIDER", "openai")
    assert isinstance(get_provider(), MockProvider)  # no key: never reaches the network
    req = [{"method": "POST", "path": "/api/cart", "status": 409, "error_code": "PINCODE_REQUIRED", "duration_ms": 5}]
    a = MockProvider().classify(SessionSummary("s", "user_fetcher", "S2", req))
    assert a == MockProvider().classify(SessionSummary("s", "user_fetcher", "S2", req))
    assert a is not None and a.blocker_id == "B05"
    unknown = MockProvider().classify(SessionSummary("s", "user_fetcher", "S2", [{**req[0], "status": 500, "error_code": None}]))
    assert unknown is not None and unknown.blocker_id == "B99" and unknown.confidence < 0.5


def test_openai_provider_parses_verdict_and_survives_errors(monkeypatch):
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        assert request.headers["authorization"] == "Bearer sk-test"
        if body.get("response_format"):
            content = json.dumps({"blocker_id": "B06", "confidence": 0.8, "rationale": "login wall"})
            return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
        return httpx.Response(500)

    provider = OpenAIProvider("sk-test", "gpt-test", client=httpx.Client(transport=httpx.MockTransport(handler)))
    summary = SessionSummary("s", "user_fetcher", "S2", [{"method": "GET", "path": "/p/x", "status": 200, "error_code": None, "duration_ms": 5}])
    verdict = provider.classify(summary)
    assert verdict is not None and verdict.blocker_id == "B06" and seen[0]["model"] == "gpt-test"
    assert provider.explain("B06", "Login wall", "evidence") is None  # HTTP error -> no text, no exception
    bad = OpenAIProvider("k", "m", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]}))))
    assert bad.classify(summary) is None


def test_llm_pass_only_touches_unexplained_sessions(synth_logs):
    con = db.connect(":memory:")
    assert pipeline.run_steps(con, ["ingest", "identify", "sessionize", "funnel"], {"source": str(synth_logs), "fmt": "jsonl"}).ok
    res = engine.diagnose(con, pipeline.RunContext("t", {"skip_site_probe": True, "llm_provider": "mock"}))
    assert res["llm_provider"] == "mock"
    rules_only = con.execute("SELECT count(*) FROM sessions WHERE diagnosis_method = 'rules'").fetchone()[0]
    assert rules_only > 0
    # every LLM-assigned session was a B99 candidate: it must carry an llm_note and no rule evidence of its own
    llm = con.execute("SELECT session_id FROM sessions WHERE diagnosis_method = 'llm'").fetchall()
    for (sid,) in llm:
        ev = json.loads(con.execute("SELECT evidence_json FROM blocker_hits WHERE session_id = ? AND is_terminal", [sid]).fetchone()[0])
        assert any(e["type"] == "llm_note" for e in ev)


def test_unknown_blocker_id_is_rejected_by_the_verdict_schema():
    from agentlens.diagnosis.llm import Verdict

    with pytest.raises(ValueError):
        Verdict(blocker_id="B42", confidence=0.9, rationale="x")
