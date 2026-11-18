"""C9/C10: the rupee impact model (PRD 14) and the ranked recommendations (PRD 15)."""

from __future__ import annotations

import json

import pytest
from agentlens import db, pipeline
from agentlens.impact import RiskInputs, compute_impact, risk
from agentlens.recommend import build_recommendations, load_blockers, priority


def test_prd_14_3_worked_example():
    """1,240 sessions x r 0.6 x p_s 0.18 x AOV Rs 2,200, scaled from a 7-day window to 30 days = about Rs 12.6 lakh."""
    res = risk(RiskInputs(sessions=1240, p_stage=0.18, aov=2200, r_low=0.4, r_base=0.6, r_high=0.8, k=30 / 7))
    assert res.risk_base == pytest.approx(1_262_674, abs=1)
    assert res.risk_base / 100_000 == pytest.approx(12.6, abs=0.05)
    assert res.recoverable_base == pytest.approx(573.9, abs=0.1)
    assert res.risk_low < res.risk_base < res.risk_high


def test_confidence_band_is_capped_and_scales_with_k():
    res = risk(RiskInputs(100, 0.95, 1000, 0.4, 0.6, 0.8, 1.0))
    assert res.risk_high == pytest.approx(100 * 0.8 * 1.0 * 1000)  # p_s + 20% is capped at 1
    assert risk(RiskInputs(100, 0.5, 1000, 0.4, 0.6, 0.8, 2.0)).risk_base == pytest.approx(2 * risk(RiskInputs(100, 0.5, 1000, 0.4, 0.6, 0.8, 1.0)).risk_base)
    assert risk(RiskInputs(0, 0.5, 1000, 0.4, 0.6, 0.8, 1.0)).risk_base == 0


def test_impact_over_the_chain(chain_db):
    rows = chain_db.execute(
        "SELECT blocker_id, stage_id, sessions_blocked, p_stage, aov, risk_low, risk_base, risk_high, low_confidence FROM impact"
    ).fetchall()
    assert rows, "the before-state scenario must price at least one blocker"
    for _, stage, n, p, aov, lo, base, hi, _low in rows:
        assert stage and n > 0 and 0 <= p <= 1 and aov > 0 and lo <= base <= hi
    # no double counting: each failed session carries exactly one terminal blocker, so the priced sessions never exceed them
    priced = sum(r[2] for r in rows)
    terminal_agents = chain_db.execute(
        "SELECT count(*) FROM sessions WHERE terminal_blocker_id IS NOT NULL AND terminal_blocker_id <> 'B99' "
        "AND identity_tier IN ('verified','declared','suspected') AND COALESCE(agent_class,'') NOT IN ('crawler','human')"
    ).fetchone()[0]
    assert priced == terminal_agents
    assert chain_db.execute("SELECT count(*) FROM impact WHERE blocker_id = 'B99'").fetchone()[0] == 0
    assert chain_db.execute("SELECT count(*) FROM impact_assumptions").fetchone()[0] == len(rows)


def _tiny_db():
    con = db.connect(":memory:")
    con.execute("DELETE FROM impact")
    return con


def test_impact_without_sessions_is_empty():
    con = _tiny_db()
    assert compute_impact(con)["blockers_priced"] == 0


def test_priority_prefers_cheap_fixes():
    weights = {"S": 1.0, "M": 2.0, "L": 4.0}
    assert priority(100_000, "S", weights) > priority(150_000, "M", weights) > priority(100_000, "L", weights)


def test_recommendations_ranked_and_complete(chain_db):
    rows = chain_db.execute(
        "SELECT rec_id, blocker_id, title, body, effort, owner, priority_score, status FROM recommendations ORDER BY priority_score DESC"
    ).fetchall()
    assert rows
    scores = [r[6] for r in rows]
    assert scores == sorted(scores, reverse=True)
    catalog = load_blockers()
    impacted = {r[0] for r in chain_db.execute("SELECT blocker_id FROM impact WHERE risk_base > 0").fetchall()}
    assert {r[1] for r in rows} == impacted
    for rec_id, blocker_id, title, body, effort, owner, _score, status in rows:
        b = json.loads(body)
        assert rec_id == f"rec-{blocker_id}" and status == "open" and title and owner
        assert effort == catalog[blocker_id]["effort"]
        assert b["what"] == catalog[blocker_id]["fix"] and b["how_to_verify"] and b["sessions_blocked"] > 0
        assert b["risk_inr_low"] <= b["risk_inr_base"] <= b["risk_inr_high"]


def test_recommend_rerun_keeps_status(synth_logs):
    con = db.connect(":memory:")
    assert pipeline.run_steps(con, None, {"source": str(synth_logs), "fmt": "jsonl", "skip_site_probe": True, "llm_provider": "off"}).ok
    rec_id = con.execute("SELECT rec_id FROM recommendations ORDER BY priority_score DESC LIMIT 1").fetchone()[0]
    con.execute("UPDATE recommendations SET status = 'in_progress' WHERE rec_id = ?", [rec_id])
    build_recommendations(con)
    assert con.execute("SELECT status FROM recommendations WHERE rec_id = ?", [rec_id]).fetchone()[0] == "in_progress"
    con.execute("DELETE FROM impact")
    build_recommendations(con)
    assert con.execute("SELECT count(*) FROM recommendations").fetchone()[0] == 0
