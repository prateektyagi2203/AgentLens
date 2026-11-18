"""C9 impact model (PRD 14): rupees at risk per terminal blocker, scaled to 30 days.

    Risk_b = L_b x r x p_s x AOV x k          k = 30 / window_days

Low/base/high use the low/base/high recoverable rate r and a +-`p_stage_band` band on p_s (capped at 1).

Choices the PRD leaves open (see docs/diagnosis.md and ADR-007):
- L_b counts agent shopping sessions (verified/declared/suspected, not crawlers) whose *terminal* blocker is b. A session
  has exactly one terminal blocker, so rupees are never double counted (IM1); secondary hits carry no rupees. B99
  (unknown) is never priced.
- The stage of a blocker is the most common stage among its terminal hits.
- p_s is the agent conversion rate among agent sessions that reached stage s. It falls back to human conversion from s
  x `agent_vs_human_factor` when fewer than `min_sample` agent sessions reached s, or fewer than `min_conversions` of them
  converted (an agent rate measured on a handful of orders, or on zero, is not a usable probability).
- window_days = calendar days spanned by session starts (override: `impact.yaml: window_days` or step param).
- `low_confidence` (IM3) when L_b < 30.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import duckdb

from . import settings
from .pipeline import RunContext, register_step

SQL_AGENTS = "{a}identity_tier IN ({tiers}) AND COALESCE({a}agent_class, '') NOT IN ({excluded})"


@dataclass(frozen=True)
class RiskInputs:
    sessions: int
    p_stage: float
    aov: float
    r_low: float
    r_base: float
    r_high: float
    k: float
    band: float = 0.2


@dataclass(frozen=True)
class Risk:
    recoverable_low: float
    recoverable_base: float
    recoverable_high: float
    risk_low: float
    risk_base: float
    risk_high: float


def risk(i: RiskInputs) -> Risk:
    """Pure PRD 14.1 formula. Recoverable = conversions per 30 days; risk = rupees per 30 days."""
    p_lo, p_hi = max(0.0, i.p_stage * (1 - i.band)), min(1.0, i.p_stage * (1 + i.band))
    base_p = min(1.0, i.p_stage)
    rec = (i.sessions * i.r_low * p_lo * i.k, i.sessions * i.r_base * base_p * i.k, i.sessions * i.r_high * p_hi * i.k)
    return Risk(rec[0], rec[1], rec[2], rec[0] * i.aov, rec[1] * i.aov, rec[2] * i.aov)


def load_config() -> dict[str, Any]:
    cfg = settings.load_yaml("impact")
    cfg.setdefault("recoverable_rate", {"low": 0.4, "base": 0.6, "high": 0.8})
    cfg.setdefault("p_stage_band", 0.2)
    cfg.setdefault("default_aov_inr", 2200)
    cfg.setdefault("agent_vs_human_factor", 1.0)
    cfg.setdefault("min_sample", 30)
    cfg.setdefault("min_conversions", 5)
    return cfg


def _q(values: list[str]) -> str:
    return ", ".join("'" + v.replace("'", "''") + "'" for v in values) or "''"


def compute_impact(con: duckdb.DuckDBPyConnection, ctx: RunContext | None = None) -> dict[str, Any]:
    from .diagnosis.engine import load_config as diag_cfg

    cfg = load_config()
    scope = diag_cfg()["scope"]
    tiers = _q(scope.get("tiers", ["verified", "declared", "suspected"]))
    excluded = _q(list(scope.get("infra_only_classes", [])) + list(scope.get("excluded_classes", [])))
    agents = SQL_AGENTS.format(a="", tiers=tiers, excluded=excluded)
    agents_s = SQL_AGENTS.format(a="s.", tiers=tiers, excluded=excluded)
    run_id = ctx.run_id if ctx else "manual"
    bounds = con.execute("SELECT min(start_ts), max(start_ts) FROM sessions").fetchone()
    con.execute("DELETE FROM impact")
    con.execute("DELETE FROM impact_assumptions")
    if not bounds or bounds[0] is None:
        return {"blockers_priced": 0, "total_risk_base": 0}
    start, end = bounds
    window_days = float((ctx.params.get("window_days") if ctx else None) or cfg.get("window_days") or 0)
    if not window_days:
        window_days = float(max(1, (end.date() - start.date()).days + 1))
    k = 30.0 / window_days

    ranks = con.execute(
        f"""
        WITH s AS (
          SELECT COALESCE(CAST(substr(max_stage, 2) AS INTEGER), 0) AS rk, converted, order_value, {agents} AS is_agent,
                 COALESCE(identity_tier, 'human') = 'human' AS is_human
          FROM sessions
        ), stages AS (SELECT unnest(generate_series(1, 8)) AS st)
        SELECT st,
               count(*) FILTER (WHERE is_agent AND rk >= st), count(*) FILTER (WHERE is_agent AND rk >= st AND converted),
               count(*) FILTER (WHERE is_human AND rk >= st), count(*) FILTER (WHERE is_human AND rk >= st AND converted)
        FROM s, stages GROUP BY st ORDER BY st
        """
    ).fetchall()
    stage_stats = {int(r[0]): (int(r[1]), int(r[2]), int(r[3]), int(r[4])) for r in ranks}
    aov_agent = con.execute(f"SELECT avg(order_value) FROM sessions WHERE converted AND {agents} AND order_value > 0").fetchone()
    aov_all = con.execute("SELECT avg(order_value) FROM sessions WHERE converted AND order_value > 0").fetchone()
    if aov_agent and aov_agent[0]:
        aov, aov_src = float(aov_agent[0]), "agent_orders"
    elif aov_all and aov_all[0]:
        aov, aov_src = float(aov_all[0]), "all_orders"
    else:
        aov, aov_src = float(cfg["default_aov_inr"]), "config_default"

    rr = cfg["recoverable_rate"]
    min_sample, min_conv = int(cfg["min_sample"]), int(cfg["min_conversions"])
    factor = float(cfg["agent_vs_human_factor"])
    blockers = con.execute(
        f"""
        SELECT s.terminal_blocker_id, count(*) AS n,
               mode(h.stage_id) AS stage_id
        FROM sessions s JOIN blocker_hits h ON h.session_id = s.session_id AND h.blocker_id = s.terminal_blocker_id AND h.is_terminal
        WHERE s.terminal_blocker_id IS NOT NULL AND s.terminal_blocker_id <> 'B99' AND {agents_s}
        GROUP BY 1 ORDER BY 1
        """
    ).fetchall()
    impact_rows: list[tuple[Any, ...]] = []
    assumption_rows: list[tuple[Any, ...]] = []
    total = 0.0
    for blocker_id, n, stage_id in blockers:
        rk = int(str(stage_id)[1:]) if stage_id else 1
        a_n, a_conv, h_n, h_conv = stage_stats.get(rk, (0, 0, 0, 0))
        if a_n >= min_sample and a_conv >= min_conv:
            p_s, p_src = a_conv / a_n, "agent"
        else:
            p_s, p_src = (h_conv / h_n if h_n else 0.0) * factor, "human_fallback"
        res = risk(RiskInputs(int(n), p_s, aov, float(rr["low"]), float(rr["base"]), float(rr["high"]), k, float(cfg["p_stage_band"])))
        total += res.risk_base
        impact_rows.append((run_id, start, end, blocker_id, stage_id, int(n), p_s, res.recoverable_low, res.recoverable_base,
                            res.recoverable_high, aov, res.risk_low, res.risk_base, res.risk_high, int(n) < min_sample))  # fmt: skip
        assumption_rows.append((run_id, blocker_id, p_src, window_days, k, aov_src, float(rr["low"]), float(rr["base"]), float(rr["high"])))
    if impact_rows:
        con.executemany("INSERT INTO impact VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", impact_rows)
        con.executemany("INSERT INTO impact_assumptions VALUES (?,?,?,?,?,?,?,?,?)", assumption_rows)
    return {"blockers_priced": len(impact_rows), "window_days": window_days, "k": round(k, 4), "aov": round(aov, 2),
            "aov_source": aov_src, "total_risk_base": round(total), "assumptions": json.dumps({"fallback": sum(1 for a in assumption_rows if a[2] != "agent")})}  # fmt: skip


def _step(con: duckdb.DuckDBPyConnection, ctx: RunContext) -> dict[str, Any]:
    return compute_impact(con, ctx)


register_step("impact", _step, replace=True)
