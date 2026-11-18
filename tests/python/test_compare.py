"""Before/after comparison (services/api/compare.py, docs/before-after.md)."""

from __future__ import annotations

from typing import Any

import pytest
from agentlens.compare import before_after, compare_windows, suggested_windows, two_proportion_z


def test_z_test_detects_a_real_lift() -> None:
    r = two_proportion_z(30, 1000, 90, 1000, min_sessions=100)
    assert r["enough_data"] and r["significant"] and r["z"] > 5 and r["p_value"] < 0.001
    assert "statistically significant" in r["note"]


def test_z_test_is_not_significant_on_noise_and_refuses_small_samples() -> None:
    noise = two_proportion_z(30, 1000, 33, 1000, min_sessions=100)
    assert noise["enough_data"] and not noise["significant"] and "noise" in noise["note"]
    small = two_proportion_z(1, 20, 5, 20, min_sessions=100)
    assert not small["enough_data"] and small["z"] is None and "at least 100" in small["note"]


def test_z_test_zero_variance_is_not_informative() -> None:
    r = two_proportion_z(0, 500, 0, 500, min_sessions=100)
    assert not r["significant"] and r["p_value"] == 1.0


def test_no_annotation_means_no_before_after(chain_db: Any) -> None:
    assert before_after(chain_db) is None
    assert suggested_windows(chain_db) == []


@pytest.fixture(scope="module")
def ba(ba_db: Any) -> dict[str, Any]:
    res = before_after(ba_db)
    assert res is not None
    return res


def test_scenario_has_a_suggested_window_around_the_config_change(ba_db: Any) -> None:
    ws = suggested_windows(ba_db)
    assert ws and ws[0]["a"]["from"] < ws[0]["a"]["to"] < ws[0]["b"]["from"] <= ws[0]["b"]["to"]


def test_agent_conversion_rises_after_the_fixes(ba: dict[str, Any]) -> None:
    h = ba["headline"]
    assert h["conversion_after"] > h["conversion_before"]
    assert h["conversion_pp"] > 2
    assert h["agent_revenue_after_inr"] > h["agent_revenue_before_inr"]
    assert h["risk_after_inr"] < h["risk_before_inr"]
    assert ba["compare"]["significance"]["significant"]


def test_fixed_blockers_drop_out_of_the_risk_table(ba: dict[str, Any]) -> None:
    by = {d["blocker_id"]: d for d in ba["blocker_deltas"]}
    for bid in ("B05", "B06"):
        assert by[bid]["risk_before_inr"] > 0 and by[bid]["risk_after_inr"] == 0


def test_compare_shape_matches_the_api_contract(ba: dict[str, Any]) -> None:
    c = ba["compare"]
    assert set(c) >= {"segment", "a", "b", "delta", "significance", "suggested_windows"}
    assert {"window", "sessions", "converted", "conversion", "agent_revenue_inr", "risk_inr", "funnel"} <= set(c["a"])
    assert {"sessions", "conversion_pp", "conversion_relative", "agent_revenue_inr", "risk_base_inr"} <= set(c["delta"])
    assert ba["control"] is not None


def test_compare_windows_is_symmetric_in_sign(ba_db: Any) -> None:
    w = suggested_windows(ba_db)[0]
    fwd = compare_windows(ba_db, w["a"]["from"], w["a"]["to"], w["b"]["from"], w["b"]["to"])
    rev = compare_windows(ba_db, w["b"]["from"], w["b"]["to"], w["a"]["from"], w["a"]["to"])
    assert fwd["significance"]["z"] == pytest.approx(-rev["significance"]["z"], abs=1e-6)
