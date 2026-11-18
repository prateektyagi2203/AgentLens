"""UA registry, suspicion signals and the identification engine end to end on small hand-built logs."""

from __future__ import annotations

import pytest
from agentlens import db
from agentlens.identify import HONEST_LIMITATION
from agentlens.identify.engine import identify
from agentlens.identify.suspicion import RunFeatures, SuspicionConfig, score_signals, suspicion_score
from agentlens.identify.ua_registry import UARegistry, declared_confidence
from agentlens.ingest import ingest_path
from agentlens.synth.signer import Signer
from helpers import BROWSER_UA, CREATED_TS, HEADLESS_UA, human_visit, rec, write_jsonl

REGISTRY = UARegistry.from_config()


def test_every_registry_token_matches_its_entry():
    assert REGISTRY.entries
    for entry in REGISTRY.entries:
        for token in entry.tokens:
            hit = REGISTRY.match(f"Mozilla/5.0 (compatible; {token}/1.0; +https://example.com/bot)")
            assert hit is not None, token
            assert hit.operator_key == entry.operator_key, token
            assert REGISTRY.match(token.upper()) is not None  # case-insensitive


def test_registry_non_agents_and_robots_only_tokens():
    assert REGISTRY.match(BROWSER_UA) is None and REGISTRY.match(None) is None and REGISTRY.match("") is None
    assert REGISTRY.match("Google-Extended") is None  # robots.txt token, never a UA
    assert REGISTRY.match("AgentLens-Replay/1.0").agent_class == "internal"
    assert REGISTRY.match("GPTBot/1.1").agent_class == "training_crawler"
    assert REGISTRY.match("ChatGPT-User/1.0").agent_class == "user_fetcher"


def test_operator_for_origin_and_ip_match():
    assert REGISTRY.operator_for_origin("https://agents.desithreads.test/")[0] == "test_operator"
    assert REGISTRY.operator_for_origin("https://nobody.example") is None
    assert declared_confidence(True) == 0.9 and declared_confidence(False) == 0.7
    assert not REGISTRY.ip_match("openai", "1.2.3.0/24")  # no ranges configured


CFG = SuspicionConfig(threshold=60)


@pytest.mark.parametrize(
    ("features", "signal", "weight"),
    [
        (RunFeatures(n_html=2, ua_browser=True, n_beacons=0, n_assets=3), "no_beacon_with_browser_ua", 25),
        (RunFeatures(n_html=2, n_assets=0, n_beacons=1), "no_assets", 15),
        (RunFeatures(n_html=1, n_assets=1, n_beacons=1, headless_hint=True), "headless_hint", 30),
        (RunFeatures(n_html=2, n_assets=1, n_beacons=1, ua_modern=True, html_missing_sec_fetch=2), "missing_sec_fetch", 10),
        (RunFeatures(n_html=5, n_assets=1, n_beacons=1, gap_cv=0.05, n_gaps=6), "regular_timing", 10),
        (RunFeatures(n_html=5, n_assets=1, n_beacons=1, n_pagelike=8, pages_per_min=30.0), "high_velocity", 10),
        (RunFeatures(n_html=1, n_assets=1, n_beacons=1, deep_link_cart_rush=True), "deep_link_cart_rush", 5),
        (RunFeatures(n_html=2, n_assets=1, n_beacons=1, ua_browser=True, atypical_accept_frac=0.9), "atypical_accept", 5),
        (RunFeatures(n_html=2, n_assets=1, n_beacons=1, invalid_signature=True), "invalid_signature", 30),
    ],
)
def test_each_suspicion_signal_fires_alone(features, signal, weight):
    fired = score_signals(features, CFG)
    assert fired.get(signal) == weight
    assert set(fired) <= {signal, "no_beacon_with_browser_ua"} or signal == "no_beacon_with_browser_ua"


def test_signals_do_not_fire_on_human_run():
    human = RunFeatures(n_html=4, n_assets=8, n_beacons=4, n_pagelike=9, ua_browser=True, ua_modern=True,
                        gap_cv=0.9, n_gaps=6, pages_per_min=3.0, atypical_accept_frac=0.0)  # fmt: skip
    assert score_signals(human, CFG) == {}
    assert suspicion_score(human, CFG) == 0


def test_score_is_sum_capped_and_thresholded():
    bot = RunFeatures(n_html=5, n_assets=0, n_beacons=0, ua_browser=True, headless_hint=True, ua_modern=True,
                      html_missing_sec_fetch=5, n_pagelike=8, pages_per_min=40.0, gap_cv=0.01, n_gaps=7,
                      deep_link_cart_rush=True, atypical_accept_frac=1.0, invalid_signature=True)  # fmt: skip
    assert suspicion_score(bot, CFG) == 100.0
    assert suspicion_score(RunFeatures(n_html=2, n_assets=0, n_beacons=0, ua_browser=True), CFG) == 40  # below 60


def _load(tmp_path, records):
    con = db.connect(":memory:")
    ingest_path(con, write_jsonl(tmp_path / "access-2026-11-01.jsonl", records))
    identify(con)
    return con


def _tier(con, rid):
    return con.execute(
        "SELECT identity_tier, operator, agent_name, agent_class, identity_confidence, signature_status "
        "FROM requests WHERE request_id = ?", [rid],
    ).fetchone()  # fmt: skip


def test_engine_declared_human_suspected_verified(tmp_path):
    signer = Signer("https://agents.desithreads.test")
    h = signer.sign("GET", "desithreads.local", "/p/x", "", CREATED_TS)
    records = [
        rec(0, request_id="declared", user_agent="Mozilla/5.0 (compatible; ChatGPT-User/1.0)", ip_hash="ip-d", accept="*/*"),
        rec(1, request_id="crawler", user_agent="Googlebot/2.1", ip_hash="ip-c"),
        rec(2, request_id="replay", user_agent="AgentLens-Replay/1.0", ip_hash="ip-r"),
        rec(3, request_id="verified", path="/p/x", user_agent="TestSignedAgent/1.0", ip_hash="ip-v",
            signature=h.signature, signature_input=h.signature_input, signature_agent=h.signature_agent),  # fmt: skip
        *human_visit(100, "cookie-h", "ip-h"),
    ]
    records += [rec(300 + i * 2, request_id=f"bot-{i}", user_agent=HEADLESS_UA, ip_hash="ip-b", path=f"/p/s{i}",
                    sec_fetch_mode=None, sec_fetch_dest=None, sec_fetch_site=None) for i in range(6)]  # fmt: skip
    con = _load(tmp_path, records)
    assert _tier(con, "declared")[:4] == ("declared", "OpenAI", "ChatGPT-User", "user_fetcher")
    assert _tier(con, "declared")[4] == 0.7
    assert _tier(con, "crawler")[0] == "declared" and _tier(con, "crawler")[3] == "search_crawler"
    assert _tier(con, "replay")[0] == "internal"
    v = _tier(con, "verified")
    assert v[0] == "verified" and v[1] == "AgentLens Test Operator" and v[5] == "valid" and v[4] == 1.0
    tiers = {r[0] for r in con.execute("SELECT identity_tier FROM requests WHERE ip_hash = 'ip-h'").fetchall()}
    assert tiers == {"human"}
    bots = con.execute("SELECT DISTINCT identity_tier, agent_class FROM requests WHERE ip_hash = 'ip-b'").fetchall()
    assert bots == [("suspected", "user_fetcher")]  # no beacons => fetcher-like


def test_forged_signature_is_not_verified_and_raises_suspicion(tmp_path):
    signer = Signer("https://agents.desithreads.test")
    h = signer.sign("GET", "desithreads.local", "/p/x", "", CREATED_TS, mode="wrong_key")
    records = [
        rec(i * 3, request_id=f"f{i}", path="/p/x", user_agent=HEADLESS_UA, ip_hash="ip-f", sec_fetch_mode=None,
            signature=h.signature, signature_input=h.signature_input, signature_agent=h.signature_agent)
        for i in range(4)
    ]  # fmt: skip
    con = _load(tmp_path, records)
    rows = con.execute("SELECT identity_tier, signature_status, suspicion_score FROM requests").fetchall()
    assert all(r[0] == "suspected" and r[1] == "invalid_sig" and r[2] >= 60 for r in rows)


def test_identify_is_idempotent(tmp_path):
    con = _load(tmp_path, human_visit(0, "c1") + human_visit(5000, "c2", "ip-2"))
    before = con.execute("SELECT request_id, identity_tier, suspicion_score FROM requests ORDER BY 1").fetchall()
    identify(con)
    assert con.execute("SELECT request_id, identity_tier, suspicion_score FROM requests ORDER BY 1").fetchall() == before


def test_honest_limitation_text_present():
    assert "browser" in HONEST_LIMITATION and "Suspected" in HONEST_LIMITATION
