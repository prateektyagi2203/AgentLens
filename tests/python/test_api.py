"""Dashboard API (M4): every endpoint against a DuckDB built from synthetic logs. Shapes follow docs/api-contract.md."""

from __future__ import annotations

import json
import shutil
import sys
import threading
import time
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from agentlens import db, pipeline, settings
from agentlens.main import app
from agentlens.routers import analytics as an
from agentlens.routers import replays as replays_router
from agentlens.routers.deps import DB
from agentlens.routers.runs import REG
from conftest import CHAIN_PARAMS
from fastapi.testclient import TestClient

RISK = {"low", "base", "high"}
WINDOW = {"from", "to", "days"}
SESSION_ROW = {
    "session_id", "start_ts", "duration_s", "request_count", "page_count", "identity_tier", "operator", "agent_name",
    "agent_class", "identity_confidence", "entry_page", "exit_page", "max_stage", "converted", "order_value_inr",
    "terminal_blocker_id", "terminal_blocker_name", "blocker_confidence", "diagnosis_method",
}  # fmt: skip
BLOCKER_ITEM = {
    "blocker_id", "name", "stage", "sessions_blocked", "share_of_failed", "risk_inr", "replay_status", "effort", "priority_score",
    "low_confidence",
}  # fmt: skip
RECOMMENDATION = {
    "rec_id", "run_id", "blocker_id", "blocker_name", "title", "body", "why_it_helps", "how_to_verify", "verify_metric", "effort",
    "owner", "priority_score", "risk_inr_base", "status", "fixed_annotation_id", "llm_explanation",
}  # fmt: skip
ANNOTATION = {"annotation_id", "ts", "type", "label", "details"}


@pytest.fixture(scope="session")
def api_template(synth_logs: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("api-template") / "agentlens.duckdb"
    con = db.connect(path)
    res = pipeline.run_steps(con, None, {"source": str(synth_logs), "fmt": "jsonl", **CHAIN_PARAMS})
    con.close()
    assert res.ok, res.steps
    return path


@pytest.fixture
def client(api_template: Path, synth_logs: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """App over a private copy of the database, config and data dir (tests may mutate all three)."""
    shutil.copy(api_template, tmp_path / "agentlens.duckdb")
    shutil.copytree(settings.REPO_ROOT / "config", tmp_path / "config")
    monkeypatch.setenv("AGENTLENS_DB_PATH", str(tmp_path / "agentlens.duckdb"))
    monkeypatch.setenv("AGENTLENS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("AGENTLENS_DATA_DIR", str(tmp_path))
    DB.reset()
    REG.reset()
    an.clear_yaml_cache()
    with TestClient(app, raise_server_exceptions=True) as c:
        c.logs = synth_logs  # type: ignore[attr-defined]
        yield c
    DB.reset()
    an.clear_yaml_cache()


def get(c: TestClient, path: str, status: int = 200, **params: Any) -> Any:
    r = c.get(f"/api{path}", params=params)
    assert r.status_code == status, r.text
    return r.json()


def assert_error(body: dict[str, Any], code: str, fields: bool = False) -> None:
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str)
    assert ("fields" in body["error"]) == fields


@pytest.fixture
def bounds(client: TestClient) -> dict[str, str]:
    return get(client, "/meta")["date_bounds"]


# ---------------------------------------------------------------- meta / health
def test_health_and_meta(client: TestClient) -> None:
    h = get(client, "/health")
    assert set(h) == {"status", "version", "time", "db", "demo_mode"} and h["status"] == "ok" and h["db"] == "ok"
    m = get(client, "/meta")
    assert set(m) == {
        "version", "demo_mode", "store_name", "currency", "operators", "agent_classes", "segments", "date_bounds", "default_window",
        "last_run",
    }  # fmt: skip
    assert m["currency"] == "INR" and m["segments"] == ["all_agents", "verified", "declared", "suspected", "humans"]
    assert m["date_bounds"]["min"] <= m["date_bounds"]["max"] and m["operators"]
    assert m["last_run"]["status"] == "succeeded" and {s["name"] for s in m["last_run"]["steps"]} >= {"ingest", "impact"}


def test_error_shapes(client: TestClient) -> None:
    assert_error(client.get("/api/nope").json(), "not_found")
    assert_error(client.delete("/api/meta").json(), "method_not_allowed")
    assert_error(client.get("/api/overview", params={"segment": "bots"}).json(), "validation_error", fields=True)
    assert_error(client.get("/api/overview", params={"from": "yesterday"}).json(), "validation_error", fields=True)


# ---------------------------------------------------------------- overview / funnel / compare
def test_overview(client: TestClient, bounds: dict[str, str]) -> None:
    o = get(client, "/overview")
    assert set(o) == {"window", "kpis", "kpi_deltas", "timeseries", "annotations", "operator_mix", "class_mix", "top_fixes"}
    assert set(o["window"]) == WINDOW and o["window"]["from"] == bounds["min"] and o["window"]["to"] == bounds["max"]
    k = o["kpis"]
    assert set(k) == {
        "agent_sessions", "total_sessions", "agent_share", "agent_converted", "agent_conversion", "human_sessions", "human_conversion",
        "agent_revenue_inr", "risk_inr", "risk_pct_of_agent_revenue", "identity_coverage", "verified_share", "diagnosis_coverage",
    }  # fmt: skip
    assert set(k["risk_inr"]) == RISK and k["risk_inr"]["low"] <= k["risk_inr"]["base"] <= k["risk_inr"]["high"]
    assert k["total_sessions"] == k["agent_sessions"] + k["human_sessions"] + (k["total_sessions"] - k["agent_sessions"] - k["human_sessions"])
    assert len(o["timeseries"]) == o["window"]["days"]
    assert set(o["timeseries"][0]) == {"date", "human", "verified", "declared", "suspected", "agent_conversion", "human_conversion"}
    assert sum(p["verified"] + p["declared"] + p["suspected"] for p in o["timeseries"]) == k["agent_sessions"]
    assert set(o["kpi_deltas"]) == set(k)
    assert o["operator_mix"] and set(o["operator_mix"][0]) == {"operator", "sessions", "share", "tier_mix"}
    assert all(0 <= v <= 1 for m in o["operator_mix"] for v in m["tier_mix"].values())
    assert {c["agent_class"] for c in o["class_mix"]} <= {"user_fetcher", "browsing_agent"}
    assert o["top_fixes"] and "B99" not in {t["blocker_id"] for t in o["top_fixes"]}
    assert set(o["top_fixes"][0]) == {
        "rec_id", "blocker_id", "blocker_name", "title", "risk_inr_base", "effort", "priority_score", "owner", "status",
    }  # fmt: skip


def test_overview_window_and_deltas(client: TestClient, bounds: dict[str, str]) -> None:
    last = get(client, "/overview", **{"from": bounds["max"], "to": bounds["max"]})
    assert last["window"]["days"] == 1 and len(last["timeseries"]) == 1
    assert all(v is None or isinstance(v, float) for v in last["kpi_deltas"].values())
    assert last["kpi_deltas"]["agent_sessions"] is not None
    humans = get(client, "/overview", segment="humans")
    assert humans["kpis"]["agent_sessions"] == 0 and humans["kpis"]["risk_inr"] == {"low": 0, "base": 0, "high": 0}
    reversed_ = get(client, "/overview", **{"from": bounds["max"], "to": bounds["min"]})
    assert reversed_["window"]["from"] == bounds["min"]


def test_empty_population_is_200(client: TestClient) -> None:
    none = {"operator": "no-such-operator"}
    assert get(client, "/overview", **none)["kpis"]["agent_sessions"] == 0
    assert get(client, "/agents", **none)["items"] == []
    b = get(client, "/blockers", **none)
    assert b["total_failed_agent_sessions"] == 0 and all(i["sessions_blocked"] == 0 for i in b["items"])
    assert get(client, "/sessions", **none)["total"] == 0
    assert get(client, "/funnel", **none)["primary"]["sessions"] == 0


def test_funnel(client: TestClient) -> None:
    f = get(client, "/funnel")
    assert set(f) == {"window", "stages", "primary", "compare", "stage_blockers"}
    assert [s["id"] for s in f["stages"]] == [f"S{i}" for i in range(1, 9)]
    assert f["primary"]["segment"] == "all_agents" and f["compare"]["segment"] == "humans"
    steps = f["primary"]["steps"]
    assert len(steps) == 8 and steps[0]["step_conversion"] == 1 and steps[0]["drop_off"] == 0
    assert [s["sessions"] for s in steps] == sorted((s["sessions"] for s in steps), reverse=True)
    assert set(steps[1]) == {"stage_id", "name", "sessions", "step_conversion", "drop_off", "overall_conversion"}
    assert set(f["stage_blockers"]) == {f"S{i}" for i in range(1, 9)}
    flat = [b for v in f["stage_blockers"].values() for b in v]
    assert flat and set(flat[0]) == {"blocker_id", "name", "sessions_blocked", "share_of_failed", "risk_inr_base"}
    v = get(client, "/funnel", segment="verified", compare="declared")
    assert v["primary"]["segment"] == "verified" and v["compare"]["segment"] == "declared"
    assert v["primary"]["sessions"] <= f["primary"]["sessions"]


def test_compare(client: TestClient, bounds: dict[str, str]) -> None:
    lo, hi = bounds["min"], bounds["max"]
    c = get(client, "/compare", a_from=lo, a_to=lo, b_from=hi, b_to=hi)
    assert set(c) == {"segment", "a", "b", "delta", "significance", "suggested_windows"}
    assert set(c["a"]) == {"window", "sessions", "converted", "conversion", "agent_revenue_inr", "risk_inr", "funnel", "blocker_shares"}
    assert set(c["delta"]) == {"sessions", "conversion_pp", "conversion_relative", "agent_revenue_inr", "risk_base_inr"}
    assert c["delta"]["sessions"] == c["b"]["sessions"] - c["a"]["sessions"]
    assert c["significance"]["test"] == "two_proportion_z"
    assert set(c["significance"]) == {"test", "enough_data", "min_sessions", "z", "p_value", "significant", "note"}
    err = client.get("/api/compare", params={"a_from": lo}).json()
    assert_error(err, "validation_error", fields=True)
    assert set(err["error"]["fields"]) == {"a_to", "b_from", "b_to"}


def test_compare_suggested_windows_follow_annotations(client: TestClient, bounds: dict[str, str]) -> None:
    day = bounds["max"]
    created = client.post("/api/annotations", json={"ts": f"{day}T08:00:00Z", "type": "config_change", "label": "Enabled pincode"})
    assert created.status_code == 201
    note = client.post("/api/annotations", json={"ts": f"{day}T09:00:00Z", "type": "note", "label": "just a note"})
    assert note.status_code == 201
    c = get(client, "/compare", a_from=bounds["min"], a_to=bounds["min"], b_from=day, b_to=day)
    sw = c["suggested_windows"]
    assert [w["annotation_id"] for w in sw] == [created.json()["annotation_id"]]
    assert set(sw[0]) == {"label", "annotation_id", "a", "b"} and sw[0]["b"]["to"] <= bounds["max"]


# ---------------------------------------------------------------- agents
def test_agents(client: TestClient) -> None:
    a = get(client, "/agents")
    assert set(a) == {"window", "items", "crawlers"} and a["items"]
    row = a["items"][0]
    assert set(row) == {
        "operator", "agent_name", "agent_class", "sessions", "share_of_agent_sessions", "pages_per_session", "conversion", "tier_mix",
        "top_blocker", "signature_status_counts", "last_seen",
    }  # fmt: skip
    assert set(row["signature_status_counts"]) == {"valid", "invalid_sig", "expired", "unknown_key", "fetch_failed", "none"}
    assert sum(row["signature_status_counts"].values()) == row["sessions"]
    assert sum(r["share_of_agent_sessions"] for r in a["items"]) == pytest.approx(1)
    assert [r["sessions"] for r in a["items"]] == sorted((r["sessions"] for r in a["items"]), reverse=True)
    assert all(c["agent_class"] in ("search_crawler", "training_crawler") for c in a["crawlers"])
    assert get(client, "/agents", segment="humans")["items"] == []
    only = get(client, "/agents", segment="verified")
    assert only["items"] and all(r["tier_mix"]["verified"] == 1 for r in only["items"])
    assert all(r["operator"] == row["operator"] for r in get(client, "/agents", operator=row["operator"])["items"])


def test_agent_detail(client: TestClient) -> None:
    row = get(client, "/agents")["items"][0]
    d = get(client, f"/agents/{row['operator']}/{row['agent_name']}")
    assert set(d) == {"window", "agent", "identity", "trend", "blockers", "recent_sessions"}
    assert d["agent"]["sessions"] == row["sessions"]
    assert set(d["identity"]) == {"user_agent_example", "signature_agent", "ip_match_rate", "avg_identity_confidence"}
    assert len(d["trend"]) == d["window"]["days"] and set(d["trend"][0]) == {"date", "sessions", "conversion"}
    assert 0 < len(d["recent_sessions"]) <= 10 and set(d["recent_sessions"][0]) == SESSION_ROW
    assert sum(t["sessions"] for t in d["trend"]) == row["sessions"]
    slugged = get(client, f"/agents/{row['operator'].lower().replace(' ', '-')}/{row['agent_name'].lower()}")
    assert slugged["agent"]["operator"] == row["operator"]
    assert_error(client.get("/api/agents/nobody/nothing").json(), "not_found")


# ---------------------------------------------------------------- blockers
def test_blockers_list(client: TestClient) -> None:
    b = get(client, "/blockers")
    assert set(b) == {"window", "total_risk_base_inr", "total_failed_agent_sessions", "diagnosis_coverage", "assumptions", "items"}
    assert set(b["assumptions"]) == {"recoverable_rate", "p_stage_band", "default_aov_inr", "window_days", "k", "min_sample"}
    assert b["assumptions"]["k"] == pytest.approx(30 / b["window"]["days"])
    items = b["items"]
    assert items and set(items[0]) == BLOCKER_ITEM
    assert sum(i["risk_inr"]["base"] for i in items) == pytest.approx(b["total_risk_base_inr"], abs=len(items))
    priced = [i for i in items if i["blocker_id"] != "B99"]
    assert [i["risk_inr"]["base"] for i in priced] == sorted((i["risk_inr"]["base"] for i in priced), reverse=True)
    assert all(i["risk_inr"]["base"] == 0 for i in items if i["blocker_id"] == "B99")
    assert all(i["low_confidence"] == (i["sessions_blocked"] < b["assumptions"]["min_sample"]) for i in items)
    assert all(i["replay_status"] == "not_run" for i in items)
    assert get(client, "/blockers", segment="humans")["items"] == []


def test_blocker_detail(client: TestClient) -> None:
    items = get(client, "/blockers")["items"]
    top = next(i for i in items if i["blocker_id"] != "B99" and i["sessions_blocked"] > 0)
    d = get(client, f"/blockers/{top['blocker_id']}")
    assert set(d) == {
        "window", "blocker", "description", "detection", "evidence", "risk_breakdown", "trend", "sample_sessions", "replays",
        "recommendation",
    }  # fmt: skip
    assert d["blocker"] == top
    assert set(d["evidence"]) == {"top_error_codes", "example_requests", "site_checks"}
    assert d["evidence"]["top_error_codes"] or d["evidence"]["example_requests"]
    for e in d["evidence"]["top_error_codes"]:
        assert set(e) == {"code", "count", "share"} and 0 < e["share"] <= 1
    rb = d["risk_breakdown"]
    assert set(rb) == {"sessions_blocked", "recoverable_rate", "p_stage", "aov_inr", "k"}
    product = rb["sessions_blocked"] * rb["recoverable_rate"] * rb["p_stage"] * rb["aov_inr"] * rb["k"]
    assert abs(product - d["blocker"]["risk_inr"]["base"]) <= 1
    assert len(d["trend"]) == d["window"]["days"] and sum(t["sessions_blocked"] for t in d["trend"]) == top["sessions_blocked"]
    assert 0 < len(d["sample_sessions"]) <= 6
    assert all(s["terminal_blocker_id"] == top["blocker_id"] for s in d["sample_sessions"])
    starts = [s["start_ts"] for s in d["sample_sessions"]]
    assert starts == sorted(starts, reverse=True)
    assert d["replays"] == [] and set(d["recommendation"]) == RECOMMENDATION


def test_blocker_detail_edge_cases(client: TestClient) -> None:
    b99 = get(client, "/blockers/B99")
    assert b99["recommendation"] is None and b99["blocker"]["risk_inr"]["base"] == 0
    zero = get(client, "/blockers/B16")
    assert zero["blocker"]["sessions_blocked"] == 0 and zero["blocker"]["risk_inr"] == {"low": 0, "base": 0, "high": 0}
    assert_error(client.get("/api/blockers/B77").json(), "not_found")


# ---------------------------------------------------------------- sessions
def test_sessions_pagination(client: TestClient) -> None:
    s = get(client, "/sessions")
    assert set(s) == {"window", "page", "page_size", "total", "items"}
    assert s["page"] == 1 and s["page_size"] == 25 and len(s["items"]) == 25 and set(s["items"][0]) == SESSION_ROW
    assert get(client, "/sessions", page_size=500)["page_size"] == 100
    p2 = get(client, "/sessions", page=2, page_size=10)
    p1 = get(client, "/sessions", page=1, page_size=10)
    assert p2["total"] == p1["total"] and not {r["session_id"] for r in p1["items"]} & {r["session_id"] for r in p2["items"]}
    last = get(client, "/sessions", page=(p1["total"] + 9) // 10, page_size=10)
    assert 0 < len(last["items"]) <= 10
    assert get(client, "/sessions", page=10_000)["items"] == []
    for bad in ({"page": 0}, {"page_size": 0}, {"sort": "nope"}, {"order": "up"}, {"converted": "maybe"}, {"max_stage": "S9"}, {"identity_tier": "x"}):
        assert_error(client.get("/api/sessions", params=bad).json(), "validation_error", fields=True)


def test_sessions_filters_and_sort(client: TestClient) -> None:
    allr = get(client, "/sessions", page_size=100)
    ver = get(client, "/sessions", identity_tier="verified", page_size=100)
    assert 0 < ver["total"] < allr["total"] and {r["identity_tier"] for r in ver["items"]} == {"verified"}
    conv = get(client, "/sessions", converted="true", segment="humans", page_size=100)
    assert conv["total"] > 0 and all(r["converted"] and r["order_value_inr"] is not None for r in conv["items"])
    assert all(r["terminal_blocker_id"] is None for r in conv["items"])
    blk = get(client, "/blockers")["items"][0]["blocker_id"]
    by_blocker = get(client, "/sessions", blocker_id=blk, page_size=100)
    assert by_blocker["total"] > 0 and {r["terminal_blocker_id"] for r in by_blocker["items"]} == {blk}
    s3 = get(client, "/sessions", max_stage="S3", page_size=100)
    assert {r["max_stage"] for r in s3["items"]} == {"S3"}
    asc = get(client, "/sessions", sort="request_count", order="asc", page_size=50)["items"]
    assert [r["request_count"] for r in asc] == sorted(r["request_count"] for r in asc)
    desc = get(client, "/sessions", sort="duration_s", order="desc", page_size=50)["items"]
    assert [r["duration_s"] for r in desc] == sorted((r["duration_s"] for r in desc), reverse=True)
    one = allr["items"][0]
    found = get(client, "/sessions", q=one["session_id"][:8].upper())
    assert one["session_id"] in {r["session_id"] for r in found["items"]}
    by_name = get(client, "/sessions", q="pincode", page_size=100)
    assert by_name["total"] == 0 or {r["terminal_blocker_id"] for r in by_name["items"]} == {"B05"}
    humans = get(client, "/sessions", segment="humans", page_size=5)
    assert humans["total"] > 0 and {r["identity_tier"] for r in humans["items"]} == {"human"}
    assert {(r["operator"], r["agent_name"], r["agent_class"]) for r in humans["items"]} == {("human", "Browser (human)", "human")}
    assert get(client, "/sessions", operator="no-such-operator")["total"] == 0


def test_session_detail(client: TestClient) -> None:
    failed = get(client, "/sessions", blocker_id=get(client, "/blockers")["items"][0]["blocker_id"], page_size=1)["items"][0]
    d = get(client, f"/sessions/{failed['session_id']}")
    assert set(d) == {"session", "identity", "requests", "stage_events", "fired_rules", "replay_ids"}
    assert d["session"] == failed
    assert set(d["identity"]) == {"signature_status", "signature_agent", "suspicion_score", "user_agent", "ip_match"}
    assert len(d["requests"]) == failed["request_count"]
    assert set(d["requests"][0]) == {
        "request_id", "ts", "offset_ms", "method", "path", "status", "duration_ms", "page_type", "error_code", "stage_id", "is_asset",
    }  # fmt: skip
    offsets = [r["offset_ms"] for r in d["requests"]]
    assert offsets[0] == 0 and offsets == sorted(offsets)
    assert d["stage_events"] and set(d["stage_events"][0]) == {"stage_id", "first_reached_ts"}
    assert [e["stage_id"] for e in d["stage_events"]][-1] == failed["max_stage"]
    terminal = [r for r in d["fired_rules"] if r["is_terminal"]]
    assert [r["blocker_id"] for r in terminal] == [failed["terminal_blocker_id"]]
    assert set(terminal[0]) == {"blocker_id", "name", "stage", "confidence", "is_terminal", "evidence"}
    assert all(e["type"] in ("request", "site_check") for r in d["fired_rules"] for e in r["evidence"])
    assert d["replay_ids"] == []
    assert_error(client.get("/api/sessions/does-not-exist").json(), "not_found")


# ---------------------------------------------------------------- annotations / recommendations
def test_annotations(client: TestClient, bounds: dict[str, str]) -> None:
    assert get(client, "/annotations") == {"items": []}
    r = client.post("/api/annotations", json={"type": "note", "label": "  Launched campaign  ", "details": {"k": 1}})
    assert r.status_code == 201 and set(r.json()) == ANNOTATION
    assert r.json()["label"] == "Launched campaign" and r.json()["details"] == {"k": 1} and r.json()["ts"].endswith("Z")
    client.post("/api/annotations", json={"type": "config_change", "label": "early", "ts": f"{bounds['min']}T00:00:00Z"})
    ts = [a["ts"] for a in get(client, "/annotations")["items"]]
    assert len(ts) == 2 and ts == sorted(ts)
    for bad in ({"type": "note"}, {"label": "x"}, {"type": "oops", "label": "x"}, {"type": "note", "label": " "},
                {"type": "note", "label": "x", "ts": "soon"}, {"type": "note", "label": "x", "details": [1]}):  # fmt: skip
        assert_error(client.post("/api/annotations", json=bad).json(), "validation_error", fields=True)


def test_recommendations(client: TestClient) -> None:
    items = get(client, "/recommendations")["items"]
    assert items and set(items[0]) == RECOMMENDATION
    assert "B99" not in {i["blocker_id"] for i in items} and all(i["status"] == "open" for i in items)
    scores = [i["priority_score"] for i in items]
    assert scores == sorted(scores, reverse=True)
    assert all(i["rec_id"] == f"rec_{i['blocker_id']}" for i in items)
    assert get(client, "/recommendations", segment="humans")["items"] == []


def test_mark_fixed_is_idempotent(client: TestClient) -> None:
    rec = get(client, "/recommendations")["items"][0]
    first = client.patch(f"/api/recommendations/{rec['rec_id']}", json={"status": "fixed"})
    assert first.status_code == 200, first.text
    body = first.json()
    assert set(body) == {"recommendation", "annotation"} and set(body["recommendation"]) == RECOMMENDATION
    assert body["recommendation"]["status"] == "fixed"
    assert body["recommendation"]["fixed_annotation_id"] == body["annotation"]["annotation_id"]
    assert body["annotation"]["type"] == "marked_fixed" and body["annotation"]["label"].startswith("Marked fixed: ")
    assert body["annotation"]["details"]["blocker_id"] == rec["blocker_id"]
    second = client.patch(f"/api/recommendations/{rec['rec_id']}", json={"status": "fixed"}).json()
    assert second["annotation"] == body["annotation"] and second["recommendation"]["status"] == "fixed"
    assert len([a for a in get(client, "/annotations")["items"] if a["type"] == "marked_fixed"]) == 1
    again = {i["blocker_id"]: i for i in get(client, "/recommendations")["items"]}
    assert again[rec["blocker_id"]]["status"] == "fixed"
    detail = get(client, f"/blockers/{rec['blocker_id']}")["recommendation"]
    assert detail["status"] == "fixed" and detail["fixed_annotation_id"] == body["annotation"]["annotation_id"]
    alias = client.patch(f"/api/recommendations/rec-{rec['blocker_id']}", json={"status": "fixed"}).json()
    assert alias["annotation"]["annotation_id"] == body["annotation"]["annotation_id"]


def test_mark_fixed_errors(client: TestClient) -> None:
    rec_id = get(client, "/recommendations")["items"][0]["rec_id"]
    assert_error(client.patch(f"/api/recommendations/{rec_id}", json={"status": "open"}).json(), "validation_error", fields=True)
    assert_error(client.patch(f"/api/recommendations/{rec_id}", json={}).json(), "validation_error", fields=True)
    assert_error(client.patch("/api/recommendations/rec_B99", json={"status": "fixed"}).json(), "not_found")
    assert_error(client.patch("/api/recommendations/rec_nope", json={"status": "fixed"}).json(), "not_found")


# ---------------------------------------------------------------- settings
def test_settings_roundtrip(client: TestClient) -> None:
    s = get(client, "/settings")
    assert set(s) == {"impact", "identification", "thresholds"}
    assert set(s["impact"]) == {"recoverable_rate", "p_stage_band", "default_aov_inr", "agent_vs_human_factor", "min_sample", "effort_weights"}
    assert set(s["identification"]) == {"signature", "suspicion", "sessions"} and len(s["identification"]["suspicion"]["weights"]) == 9
    assert set(s["thresholds"]) == {"slow_response_ms", "significance_min_sessions"}
    before = get(client, "/overview")["kpis"]["risk_inr"]
    s["impact"]["recoverable_rate"] = {"low": 0.1, "base": 0.2, "high": 0.3}
    s["thresholds"]["significance_min_sessions"] = 50
    r = client.put("/api/settings", json=s)
    assert r.status_code == 200 and r.json() == s and get(client, "/settings") == s
    after = get(client, "/overview")["kpis"]["risk_inr"]
    assert after["base"] < before["base"]
    assert get(client, "/blockers")["assumptions"]["recoverable_rate"]["base"] == 0.2
    saved = settings.load_yaml("impact")
    assert saved["recoverable_rate"]["base"] == 0.2 and "min_conversions" in saved
    assert settings.load_yaml("diagnosis")["thresholds"]["significance_min_sessions"] == 50


def test_settings_validation(client: TestClient) -> None:
    s = get(client, "/settings")
    s["impact"]["recoverable_rate"]["low"] = 0.9
    s["impact"]["min_sample"] = 2.5
    s["impact"]["effort_weights"]["S"] = 9
    s["identification"]["signature"]["clock_skew_s"] = 9999
    s["identification"]["suspicion"]["weights"]["no_assets"] = "lots"
    s["thresholds"]["slow_response_ms"] = 5
    r = client.put("/api/settings", json=s)
    assert r.status_code == 422
    assert_error(r.json(), "validation_error", fields=True)
    assert set(r.json()["error"]["fields"]) == {
        "impact.recoverable_rate.low", "impact.min_sample", "impact.effort_weights.M", "identification.signature.clock_skew_s",
        "identification.suspicion.weights.no_assets", "thresholds.slow_response_ms",
    }  # fmt: skip
    assert get(client, "/settings")["impact"]["recoverable_rate"]["low"] == 0.4
    partial = client.put("/api/settings", json={"impact": {}})
    assert partial.status_code == 422 and "impact.p_stage_band" in partial.json()["error"]["fields"]


# ---------------------------------------------------------------- eval / report / site checks
def test_eval_latest(client: TestClient, tmp_path: Path) -> None:
    assert_error(client.get("/api/eval/latest").json(), "not_found")
    doc = {"run_id": "eval-1", "ts": "2026-01-01T00:00:00Z", "dataset": "x"}
    (tmp_path / "eval").mkdir()
    (tmp_path / "eval" / "latest.json").write_text(json.dumps(doc), encoding="utf-8")
    assert get(client, "/eval/latest") == doc


def test_eval_builder_shape(api_template: Path, synth_logs: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agentlens.eval.latest import build_latest

    monkeypatch.setenv("AGENTLENS_DATA_DIR", str(synth_logs.parent))
    shutil.copy(api_template, tmp_path / "e.duckdb")
    con = db.connect(tmp_path / "e.duckdb")
    try:
        doc = build_latest(con, synth_logs)
    finally:
        con.close()
    assert set(doc) == {"run_id", "ts", "dataset", "identification", "diagnosis", "impact", "replay", "notes"}
    cm = doc["identification"]["confusion"]
    assert len(cm) == 4 and all(len(r) == 4 for r in cm) and sum(map(sum, cm)) > 0
    assert 0 <= doc["identification"]["tier_accuracy"] <= 1 and doc["impact"] == {"mean_abs_pct_error": None}
    assert doc["diagnosis"]["per_blocker"] and set(doc["diagnosis"]["per_blocker"][0]) == {"blocker_id", "precision", "recall", "f1", "support"}


def test_site_checks(client: TestClient) -> None:
    assert set(get(client, "/site-checks")) == {"items"}


def test_report_contract(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    assert_error(client.get("/api/report", params={"format": "docx"}).json(), "bad_request")
    monkeypatch.setitem(sys.modules, "agentlens.report", None)
    assert client.get("/api/report").status_code == 501
    assert_error(client.get("/api/report").json(), "not_implemented")
    seen: dict[str, Any] = {}

    def build_report(con: Any, fmt: str, filters: dict[str, Any]) -> tuple[bytes, str]:
        seen.update(fmt=fmt, filters=filters)
        return b"# report", "text/markdown"

    monkeypatch.setitem(sys.modules, "agentlens.report", types.SimpleNamespace(build_report=build_report))
    r = client.get("/api/report", params={"format": "md", "segment": "verified"})
    assert r.status_code == 200 and r.content == b"# report" and r.headers["content-type"].startswith("text/markdown")
    assert r.headers["content-disposition"] == 'attachment; filename="agent-readiness-report.md"'
    assert seen["fmt"] == "md" and seen["filters"]["segment"] == "verified"


def test_report_md_end_to_end(client: TestClient) -> None:
    r = client.get("/api/report", params={"format": "md"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/markdown") and len(r.content) > 200


# ---------------------------------------------------------------- replays
def test_replays_read(client: TestClient, tmp_path: Path) -> None:
    assert get(client, "/replays") == {"items": []}
    assert_error(client.get("/api/replays/nope").json(), "not_found")
    sid = get(client, "/sessions", blocker_id=get(client, "/blockers")["items"][0]["blocker_id"], page_size=1)["items"][0]["session_id"]
    shots = tmp_path / "shots"
    shots.mkdir()
    (shots / "step_1.png").write_bytes(b"png")
    doc = {
        "verdict": "confirmed", "user_agent": "ReplayBot/1", "signed_requests": True,
        "steps": [{"n": 1, "action": "GET /", "method": "GET", "url": "https://s/", "status": 200, "duration_ms": 12, "note": "ok",
                   "screenshot_url": "/api/replays/rp1/screenshots/step_1.png"}],
        "network_log": [{"ts": "2026-01-01T00:00:00Z", "method": "GET", "url": "https://s/", "status": 200, "duration_ms": 12, "error_code": None}],
    }  # fmt: skip
    with DB.write() as w:
        w.execute(
            "INSERT INTO replays VALUES ('rp1', 'B05', ?, 'browser', 'completed', now()::TIMESTAMP, now()::TIMESTAMP, ?, ?, 'blocked at pincode')",
            [sid, json.dumps(doc), str(shots)],
        )
    rows = get(client, "/replays")["items"]
    assert len(rows) == 1 and rows[0]["verdict"] == "confirmed" and rows[0]["steps_count"] == 1 and rows[0]["status"] == "completed"
    assert set(rows[0]) == {
        "replay_id", "blocker_id", "blocker_name", "source_session_id", "mode", "status", "verdict", "started_at", "finished_at",
        "steps_count", "verdict_explanation",
    }  # fmt: skip
    d = get(client, "/replays/rp1")
    assert set(d) == {"replay", "user_agent", "signed_requests", "steps", "network_log", "explanation"}
    assert d["signed_requests"] is True and d["steps"][0]["screenshot_url"].endswith("step_1.png") and d["explanation"] == "blocked at pincode"
    assert client.get("/api/replays/rp1/screenshots/step_1.png").content == b"png"
    assert client.get("/api/replays/rp1/screenshots/..%2Fsecret.txt").status_code == 404
    assert client.get("/api/replays/rp1/screenshots/missing.png").status_code == 404
    assert get(client, f"/sessions/{sid}")["replay_ids"] == ["rp1"]
    assert get(client, "/blockers/B05")["replays"][0]["replay_id"] == "rp1"
    assert {i["blocker_id"]: i["replay_status"] for i in get(client, "/blockers")["items"]}.get("B05", "confirmed") == "confirmed"


# ---------------------------------------------------------------- runs
def wait_run(c: TestClient, run_id: str, timeout: float = 120) -> dict[str, Any]:
    end = time.time() + timeout
    while time.time() < end:
        run = get(c, f"/runs/{run_id}")
        if run["status"] in ("succeeded", "failed"):
            return run  # type: ignore[no-any-return]
        time.sleep(0.2)
    raise AssertionError("run did not finish")


def test_pipeline_run_executes(client: TestClient) -> None:
    r = client.post("/api/pipeline/run", json={"source": str(client.logs), "skip_site_probe": True, "llm_provider": "off"})  # type: ignore[attr-defined]
    assert r.status_code == 202 and set(r.json()) == {"run_id", "status"} and r.json()["status"] == "queued"
    run = wait_run(client, r.json()["run_id"])
    assert run["status"] == "succeeded", run
    assert set(run) == {"run_id", "kind", "status", "started_at", "finished_at", "steps", "counts", "error"} and run["kind"] == "pipeline"
    assert [s["name"] for s in run["steps"]] == list(pipeline.CANONICAL_ORDER) and all(s["status"] == "succeeded" for s in run["steps"])
    assert get(client, "/meta")["last_run"]["run_id"] == run["run_id"]
    assert_error(client.get("/api/runs/unknown").json(), "not_found")


def test_concurrent_runs_conflict(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    gate = threading.Event()

    def slow(con: Any, steps: Any, params: Any) -> Any:
        gate.wait(10)
        return types.SimpleNamespace(ok=True, steps=[], run_id=params.get("run_id"))

    monkeypatch.setattr(pipeline, "run_steps", slow)
    monkeypatch.setattr(replays_router, "_runner", lambda: types.SimpleNamespace(run_replays=lambda *a, **k: {"replays": 0}))
    try:
        first = client.post("/api/pipeline/run", json={})
        assert first.status_code == 202
        running = get(client, f"/runs/{first.json()['run_id']}")
        assert running["status"] in ("queued", "running")
        for path in ("/api/pipeline/run", "/api/replays/run", "/api/ingest"):
            second = client.post(path, json={})
            assert second.status_code == 409, path
            assert_error(second.json(), "run_in_progress")
        started = time.time()
        assert get(client, "/overview")["kpis"]["agent_sessions"] > 0 and time.time() - started < 5
    finally:
        gate.set()
    assert wait_run(client, first.json()["run_id"], 30)["status"] == "succeeded"
    assert client.post("/api/replays/run", json={}).status_code == 202


def test_replay_run_validation_and_fallback(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(replays_router, "_runner", lambda: None)
    assert_error(client.post("/api/replays/run", json={}).json(), "not_implemented")
    monkeypatch.setattr(replays_router, "_runner", lambda: types.SimpleNamespace(run_replays=lambda *a, **k: {"replays": 0}))
    bad = client.post("/api/replays/run", json={"blocker_id": "B99", "top_n": 0})
    assert bad.status_code == 422 and set(bad.json()["error"]["fields"]) == {"blocker_id", "top_n"}
    ok = client.post("/api/replays/run", json={"blocker_id": "B05"})
    assert ok.status_code == 202
    run = wait_run(client, ok.json()["run_id"], 30)
    assert run["kind"] == "replay" and [s["name"] for s in run["steps"]] == ["select", "replay", "verdict"] and run["status"] == "succeeded"

    def fake(con: Any, *, blocker_id: Any = None, top_n: Any = None, on_step: Any = None) -> dict[str, int]:
        assert blocker_id == "B05" and top_n is None
        for name in ("select", "replay", "verdict"):
            on_step(name, "running", None)
            on_step(name, "succeeded", f"{name} done")
        return {"replays": 1, "confirmed": 1}

    monkeypatch.setattr(replays_router, "_runner", lambda: types.SimpleNamespace(run_replays=fake))
    run = wait_run(client, client.post("/api/replays/run", json={"blocker_id": "B05"}).json()["run_id"], 30)
    assert [s["message"] for s in run["steps"]] == ["select done", "replay done", "verdict done"]
    assert run["counts"] == {"replay.replays": 1, "replay.confirmed": 1}


def test_ingest_validation(client: TestClient) -> None:
    assert_error(client.post("/api/ingest", json={"format": "csv"}).json(), "validation_error", fields=True)
