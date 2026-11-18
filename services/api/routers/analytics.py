"""Read-side analytics behind the dashboard endpoints: populations, KPIs, funnels and the live impact model.

The pipeline's `impact` table prices the *whole* data window once. The dashboard needs any window and any
segment/operator/class filter, so risk is recomputed here from `sessions` + `blocker_hits` with the same formula
(`agentlens.impact.risk`) and the same p_stage rules (agent conversion past the stage, human fallback when thin). Everything
is a handful of aggregate scans over `sessions`, which stays fast at 100k sessions.

Ground truth is never read here (PRD 12.6): only `agentlens.eval` may.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, TypeVar, cast

import duckdb
import yaml

from .. import db, settings
from ..impact import RiskInputs, risk
from .deps import DB, STAGE_IDS, Filters, Window

T = TypeVar("T")

CRAWLER_CLASSES = ("search_crawler", "training_crawler")
TIERS = ("verified", "declared", "suspected")
SIGNATURE_STATUSES = ("valid", "invalid_sig", "expired", "unknown_key", "fetch_failed", "none")
DEFAULT_EFFORT_WEIGHTS = {"S": 1.0, "M": 2.0, "L": 4.0}

_YAML_CACHE: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}
_MEMO: dict[tuple[Any, ...], Any] = {}
_MEMO_LOCK = threading.Lock()
_MEMO_MAX = 256


def clear_yaml_cache() -> None:
    _YAML_CACHE.clear()
    clear_memo()


def clear_memo() -> None:
    with _MEMO_LOCK:
        _MEMO.clear()


def _memo(name: str, ctx: Ctx, f: Filters, w: Window, extra: tuple[Any, ...], compute: Callable[[], T]) -> T:
    """Aggregates are pure functions of (DB write version, config, filters, window): a dashboard page load asks the same
    questions from several endpoints, and a write (run, PATCH, annotation) bumps `DB.version` and so drops them all."""
    key = (DB.version, name, ctx.agent_sql(), repr(ctx.impact), repr(ctx.catalog), f.segment, f.operator, f.agent_class, w.from_, w.to, *extra)
    with _MEMO_LOCK:
        if key in _MEMO:
            return cast(T, _MEMO[key])
    value = compute()
    with _MEMO_LOCK:
        if len(_MEMO) >= _MEMO_MAX:
            _MEMO.clear()
        _MEMO[key] = value
    return value


def yaml_cached(name: str) -> dict[str, Any]:
    """config/<name>.yaml, re-read only when the file changes (so Settings edits apply immediately)."""
    path: Path = settings.config_dir() / f"{name}.yaml"
    st = path.stat()
    stamp = (st.st_mtime_ns, st.st_size)
    hit = _YAML_CACHE.get(str(path))
    if hit and hit[0] == stamp:
        return hit[1]
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    _YAML_CACHE[str(path)] = (stamp, data)
    return data


@dataclass
class Ctx:
    """Config snapshot for one request."""

    tiers: list[str]
    excluded_classes: list[str]
    impact: dict[str, Any]
    catalog: dict[str, dict[str, Any]]
    min_sessions: int

    def agent_sql(self, a: str = "") -> str:
        tiers = ", ".join(f"'{t}'" for t in self.tiers) or "''"
        excl = ", ".join(f"'{c}'" for c in self.excluded_classes) or "''"
        return f"({a}identity_tier IN ({tiers}) AND COALESCE({a}agent_class, '') NOT IN ({excl}))"

    @property
    def effort_weights(self) -> dict[str, float]:
        return {k: float(v) for k, v in self.impact.get("effort_weights", DEFAULT_EFFORT_WEIGHTS).items()}


def load_ctx() -> Ctx:
    diag = yaml_cached("diagnosis")
    scope = diag.get("scope", {}) or {}
    thresholds = diag.get("thresholds", {}) or {}
    imp = dict(yaml_cached("impact"))
    imp.setdefault("recoverable_rate", {"low": 0.4, "base": 0.6, "high": 0.8})
    imp.setdefault("p_stage_band", 0.2)
    imp.setdefault("default_aov_inr", 2200)
    imp.setdefault("agent_vs_human_factor", 1.0)
    imp.setdefault("min_sample", 30)
    imp.setdefault("min_conversions", 5)
    imp.setdefault("effort_weights", DEFAULT_EFFORT_WEIGHTS)
    return Ctx(
        tiers=list(scope.get("tiers", list(TIERS))),
        excluded_classes=list(scope.get("infra_only_classes", [])) + list(scope.get("excluded_classes", [])),
        impact=imp,
        catalog=dict(yaml_cached("blockers").get("blockers", {})),
        min_sessions=int(thresholds.get("significance_min_sessions", 100)),
    )


def blocker_meta(ctx: Ctx, blocker_id: str) -> dict[str, Any]:
    m = ctx.catalog.get(blocker_id) or {}
    return {
        "name": m.get("name", blocker_id), "stage": m.get("stage", "ANY"), "description": m.get("description", ""),
        "fix": m.get("fix", ""), "how_to_verify": m.get("how_to_verify", ""), "effort": m.get("effort", "M"),
        "owner": m.get("owner", "Eng"),
    }  # fmt: skip


def blocker_name(ctx: Ctx, blocker_id: str | None) -> str | None:
    return blocker_meta(ctx, blocker_id)["name"] if blocker_id else None


# ---------------------------------------------------------------- populations
def population(
    ctx: Ctx, f: Filters, w: Window | None, *, segment: str | None = None, alias: str = "", filters: bool = True,
) -> tuple[str, list[Any]]:  # fmt: skip
    """SQL predicate + params selecting the sessions of a segment in a window (operator/class apply to agents only)."""
    seg = segment or f.segment
    a = f"{alias}." if alias else ""
    conds: list[str] = []
    params: list[Any] = []
    if w is not None:
        conds.append(f"CAST({a}start_ts AS DATE) BETWEEN ? AND ?")
        params += [w.from_, w.to]
    if seg == "humans":
        conds.append(f"COALESCE({a}identity_tier, 'human') = 'human'")
    else:
        conds.append(ctx.agent_sql(a))
        if seg in TIERS:
            conds.append(f"{a}identity_tier = '{seg}'")
        if filters and f.operator:
            conds.append(f"{a}operator = ?")
            params.append(f.operator)
        if filters and f.agent_class:
            conds.append(f"{a}agent_class = ?")
            params.append(f.agent_class)
    return " AND ".join(conds), params


def stage_rank(stage: str | None) -> int:
    return int(stage[1:]) if stage and re.fullmatch(r"S[1-8]", stage) else 0


def totals(cur: duckdb.DuckDBPyConnection, ctx: Ctx, f: Filters, w: Window, segment: str | None = None, filters: bool = True) -> dict[str, Any]:
    out = _memo("totals", ctx, f, w, (segment, filters), lambda: _totals(cur, ctx, f, w, segment, filters))
    return {**out, "tiers": dict(out["tiers"])}


def _totals(cur: duckdb.DuckDBPyConnection, ctx: Ctx, f: Filters, w: Window, segment: str | None, filters: bool) -> dict[str, Any]:
    where, params = population(ctx, f, w, segment=segment, filters=filters)
    row = cur.execute(
        f"""
        SELECT count(*), count(*) FILTER (WHERE converted), COALESCE(sum(order_value) FILTER (WHERE converted), 0),
               COALESCE(sum(page_count), 0), count(*) FILTER (WHERE identity_tier = 'verified'),
               count(*) FILTER (WHERE identity_tier = 'declared'), count(*) FILTER (WHERE identity_tier = 'suspected'),
               count(*) FILTER (WHERE NOT converted AND terminal_blocker_id IS NOT NULL AND terminal_blocker_id <> 'B99')
        FROM sessions WHERE {where}
        """,
        params,
    ).fetchone()
    assert row is not None
    n, conv, revenue, pages, v, d, s, diagnosed = (int(row[0]), int(row[1]), float(row[2]), int(row[3]), *map(int, row[4:]))
    return {
        "sessions": n, "converted": conv, "revenue": revenue, "pages": pages, "failed": n - conv, "diagnosed": diagnosed,
        "tiers": {"verified": v, "declared": d, "suspected": s},
    }  # fmt: skip


def reach(cur: duckdb.DuckDBPyConnection, ctx: Ctx, f: Filters, w: Window, segment: str) -> list[int]:
    return list(_memo("reach", ctx, f, w, (segment,), lambda: _reach(cur, ctx, f, w, segment)))


def _reach(cur: duckdb.DuckDBPyConnection, ctx: Ctx, f: Filters, w: Window, segment: str) -> list[int]:
    """Sessions that reached stage n or later, n = 1..8 (stage 1 counts every session: it is the denominator)."""
    where, params = population(ctx, f, w, segment=segment)
    rows = cur.execute(
        f"SELECT COALESCE(CAST(substr(max_stage, 2) AS INTEGER), 0) AS rk, count(*) FROM sessions WHERE {where} GROUP BY 1",
        params,
    ).fetchall()
    by_rank = {int(r[0]): int(r[1]) for r in rows}
    total = sum(by_rank.values())
    out = [total]
    for n in range(2, 9):
        out.append(sum(c for rk, c in by_rank.items() if rk >= n))
    return out


def funnel_series(segment: str, reached: list[int], names: dict[str, str]) -> dict[str, Any]:
    first = reached[0]
    steps = []
    for i, sid in enumerate(STAGE_IDS):
        steps.append({
            "stage_id": sid, "name": names.get(sid, sid), "sessions": reached[i],
            "step_conversion": 1.0 if i == 0 else (reached[i] / reached[i - 1] if reached[i - 1] else 0.0),
            "drop_off": 0.0 if i == 0 else (1 - reached[i] / reached[i - 1] if reached[i - 1] else 0.0),
            "overall_conversion": reached[i] / first if first else 0.0,
        })  # fmt: skip
    return {"segment": segment, "sessions": first, "conversion": reached[7] / first if first else 0.0, "steps": steps}


def stage_defs() -> list[dict[str, str]]:
    cfg = yaml_cached("funnel")
    names = {s["id"]: s["name"] for s in cfg.get("stages", [])}
    return [{"id": sid, "name": names.get(sid, sid)} for sid in STAGE_IDS]


def timeseries(cur: duckdb.DuckDBPyConnection, ctx: Ctx, f: Filters, w: Window) -> list[dict[str, Any]]:
    ag, ag_params = population(ctx, f, None)
    if f.segment == "humans":
        ag, ag_params = "false", []
    rows = cur.execute(
        f"""
        WITH s AS (
          SELECT CAST(start_ts AS DATE) AS d, identity_tier AS t, converted AS c,
                 COALESCE(identity_tier, 'human') = 'human' AS hu, ({ag}) AS ag
          FROM sessions WHERE CAST(start_ts AS DATE) BETWEEN ? AND ?
        )
        SELECT d, count(*) FILTER (WHERE hu), count(*) FILTER (WHERE hu AND c),
               count(*) FILTER (WHERE ag AND t = 'verified'), count(*) FILTER (WHERE ag AND t = 'declared'),
               count(*) FILTER (WHERE ag AND t = 'suspected'), count(*) FILTER (WHERE ag), count(*) FILTER (WHERE ag AND c)
        FROM s GROUP BY d ORDER BY d
        """,
        [*ag_params, w.from_, w.to],
    ).fetchall()
    by_day = {r[0].isoformat(): r for r in rows}
    out = []
    from datetime import date, timedelta

    day = date.fromisoformat(w.from_)
    end = date.fromisoformat(w.to)
    while day <= end:
        r = by_day.get(day.isoformat())
        if r:
            out.append({
                "date": day.isoformat(), "human": int(r[1]), "verified": int(r[3]), "declared": int(r[4]),
                "suspected": int(r[5]), "agent_conversion": r[7] / r[6] if r[6] else 0.0,
                "human_conversion": r[2] / r[1] if r[1] else 0.0,
            })  # fmt: skip
        else:
            out.append({"date": day.isoformat(), "human": 0, "verified": 0, "declared": 0, "suspected": 0,
                        "agent_conversion": 0.0, "human_conversion": 0.0})  # fmt: skip
        day += timedelta(days=1)
    return out


# ---------------------------------------------------------------- replays
def replay_verdict(steps_json: str | None) -> str | None:
    """Verdict stored by the replay runner inside `replays.steps_json` (an object); None when absent."""
    if not steps_json:
        return None
    try:
        doc = json.loads(steps_json)
    except (TypeError, ValueError):
        return None
    v = doc.get("verdict") if isinstance(doc, dict) else None
    return v if v in ("confirmed", "not_confirmed", "inconclusive") else None


def replay_status_map(cur: duckdb.DuckDBPyConnection) -> dict[str, str]:
    rows = cur.execute("SELECT blocker_id, status, steps_json FROM replays ORDER BY started_at, replay_id").fetchall()
    out: dict[str, str] = {}
    for bid, status, steps in rows:
        if status in ("queued", "running"):
            out[bid] = "pending"
        elif status == "completed":
            out[bid] = replay_verdict(steps) or "inconclusive"
        elif status == "failed":
            out[bid] = "inconclusive"
    return out


# ---------------------------------------------------------------- impact
@dataclass
class BlockerImpact:
    blocker_id: str
    name: str
    stage: str
    sessions_blocked: int
    share_of_failed: float
    low: int
    base: int
    high: int
    effort: str
    priority_score: int
    low_confidence: bool
    replay_status: str
    p_stage: float
    owner: str

    def item(self) -> dict[str, Any]:
        return {
            "blocker_id": self.blocker_id, "name": self.name, "stage": self.stage, "sessions_blocked": self.sessions_blocked,
            "share_of_failed": self.share_of_failed, "risk_inr": {"low": self.low, "base": self.base, "high": self.high},
            "replay_status": self.replay_status, "effort": self.effort, "priority_score": self.priority_score,
            "low_confidence": self.low_confidence,
        }  # fmt: skip


@dataclass
class ImpactResult:
    items: list[BlockerImpact] = field(default_factory=list)
    failed: int = 0
    diagnosed: int = 0
    aov: float = 0.0
    k: float = 1.0
    revenue: float = 0.0
    converted: int = 0
    sessions: int = 0

    @property
    def coverage(self) -> float:
        return self.diagnosed / self.failed if self.failed else 1.0

    def risk_total(self) -> dict[str, int]:
        return {
            "low": sum(i.low for i in self.items), "base": sum(i.base for i in self.items),
            "high": sum(i.high for i in self.items),
        }  # fmt: skip

    def get(self, blocker_id: str) -> BlockerImpact | None:
        return next((i for i in self.items if i.blocker_id == blocker_id), None)


def stage_conversion(cur: duckdb.DuckDBPyConnection, ctx: Ctx, f: Filters, w: Window, segment: str) -> dict[int, tuple[int, int, int, int]]:
    return _memo("stage_conversion", ctx, f, w, (segment,), lambda: _stage_conversion(cur, ctx, f, w, segment))


def _stage_conversion(cur: duckdb.DuckDBPyConnection, ctx: Ctx, f: Filters, w: Window, segment: str) -> dict[int, tuple[int, int, int, int]]:
    """Per stage s: (agent sessions reaching s, of which converted, human reaching s, converted)."""
    ag, ag_params = population(ctx, f, None, segment=segment)
    rows = cur.execute(
        f"""
        WITH s AS (
          SELECT COALESCE(CAST(substr(max_stage, 2) AS INTEGER), 0) AS rk, converted AS c,
                 COALESCE(identity_tier, 'human') = 'human' AS hu, ({ag}) AS ag
          FROM sessions WHERE CAST(start_ts AS DATE) BETWEEN ? AND ?
        )
        SELECT rk, ag, hu, c, count(*) FROM s WHERE ag OR hu GROUP BY ALL
        """,
        [*ag_params, w.from_, w.to],
    ).fetchall()
    out: dict[int, tuple[int, int, int, int]] = {}
    for st in range(1, 9):
        a_n = a_c = h_n = h_c = 0
        for rk, is_ag, is_hu, conv, n in rows:
            if rk < st:
                continue
            if is_ag:
                a_n += n
                a_c += n if conv else 0
            if is_hu:
                h_n += n
                h_c += n if conv else 0
        out[st] = (a_n, a_c, h_n, h_c)
    return out


def compute_impact(cur: duckdb.DuckDBPyConnection, ctx: Ctx, f: Filters, w: Window, segment: str | None = None) -> ImpactResult:
    res = _memo("impact", ctx, f, w, (segment,), lambda: _compute_impact(cur, ctx, f, w, segment))
    return replace(res, items=list(res.items))


def _compute_impact(cur: duckdb.DuckDBPyConnection, ctx: Ctx, f: Filters, w: Window, segment: str | None) -> ImpactResult:
    """Priced blockers for a window/segment (PRD 14), scaled to 30 days; B99 is listed but never priced."""
    seg = segment or f.segment
    res = ImpactResult()
    if seg == "humans":
        return res
    tot = totals(cur, ctx, f, w, segment=seg)
    res.failed, res.diagnosed, res.converted, res.revenue, res.sessions = (
        tot["failed"], tot["diagnosed"], tot["converted"], tot["revenue"], tot["sessions"],
    )  # fmt: skip
    cfgi = ctx.impact
    res.k = 30.0 / max(1, w.days)
    res.aov = res.revenue / res.converted if res.converted else float(cfgi["default_aov_inr"])
    where, params = population(ctx, f, w, segment=seg, alias="s")
    rows = cur.execute(
        f"""
        SELECT s.terminal_blocker_id, count(DISTINCT s.session_id), mode(h.stage_id)
        FROM sessions s LEFT JOIN blocker_hits h
          ON h.session_id = s.session_id AND h.blocker_id = s.terminal_blocker_id AND h.is_terminal
        WHERE s.terminal_blocker_id IS NOT NULL AND NOT s.converted AND {where}
        GROUP BY 1
        """,
        params,
    ).fetchall()
    if not rows:
        return res
    stats = stage_conversion(cur, ctx, f, w, seg)
    replays = replay_status_map(cur)
    rr, band = cfgi["recoverable_rate"], float(cfgi["p_stage_band"])
    min_sample, min_conv, factor = int(cfgi["min_sample"]), int(cfgi["min_conversions"]), float(cfgi["agent_vs_human_factor"])
    weights = ctx.effort_weights
    for bid, n, mode_stage in rows:
        meta = blocker_meta(ctx, bid)
        stage = mode_stage if stage_rank(mode_stage) else _first_stage(meta["stage"])
        a_n, a_c, h_n, h_c = stats[stage_rank(stage)]
        if a_n >= min_sample and a_c >= min_conv:
            p = a_c / a_n
        else:
            p = (h_c / h_n if h_n else 0.0) * factor
        if bid == "B99":
            low = base = high = 0
        else:
            r = risk(RiskInputs(int(n), p, res.aov, float(rr["low"]), float(rr["base"]), float(rr["high"]), res.k, band))
            low, base, high = round(r.risk_low), round(r.risk_base), round(r.risk_high)
        effort = str(meta["effort"])
        res.items.append(BlockerImpact(
            bid, meta["name"], stage, int(n), int(n) / res.failed if res.failed else 0.0, low, base, high, effort,
            round(base / weights.get(effort, weights.get("M", 2.0))), int(n) < min_sample, replays.get(bid, "not_run"),
            min(1.0, p), str(meta["owner"]),
        ))  # fmt: skip
    res.items.sort(key=lambda i: (i.blocker_id == "B99", -i.base, -i.sessions_blocked, i.blocker_id))
    return res


def _first_stage(catalog_stage: str) -> str:
    m = re.search(r"S[1-8]", str(catalog_stage))
    return m.group(0) if m else "S1"


def empty_item(ctx: Ctx, blocker_id: str, replay_status: str) -> BlockerImpact:
    meta = blocker_meta(ctx, blocker_id)
    return BlockerImpact(
        blocker_id, meta["name"], _first_stage(meta["stage"]), 0, 0.0, 0, 0, 0, str(meta["effort"]), 0, True, replay_status, 0.0,
        str(meta["owner"]),
    )  # fmt: skip


def risk_range(res: ImpactResult) -> dict[str, int]:
    return res.risk_total()


# ---------------------------------------------------------------- sessions
def session_row(ctx: Ctx, r: tuple[Any, ...]) -> dict[str, Any]:
    """Row from `SESSION_COLUMNS` -> SessionRow."""
    from .deps import iso

    (sid, start, dur, reqs, pages, tier, op, name, cls, conf, entry, exit_, stage, conv, value, bid, bconf, method) = r
    human = tier == "human" or tier is None
    return {
        "session_id": sid, "start_ts": iso(start), "duration_s": float(dur or 0), "request_count": int(reqs or 0),
        "page_count": int(pages or 0), "identity_tier": tier or "human",
        "operator": "human" if human else (op or "unknown"), "agent_name": "Browser (human)" if human else (name or "unknown"),
        "agent_class": "human" if human else (cls or "browsing_agent"), "identity_confidence": float(conf or 0),
        "entry_page": entry or "", "exit_page": exit_ or "", "max_stage": stage, "converted": bool(conv),
        "order_value_inr": float(value) if conv and value is not None else None, "terminal_blocker_id": bid,
        "terminal_blocker_name": blocker_name(ctx, bid), "blocker_confidence": float(bconf) if bconf is not None else None,
        "diagnosis_method": {"rules": "rule", "rule": "rule", "llm": "llm"}.get(method or "", "none"),
    }  # fmt: skip


SESSION_COLUMNS = (
    "{a}session_id, {a}start_ts, {a}duration_s, {a}request_count, {a}page_count, {a}identity_tier, {a}operator, "
    "{a}agent_name, {a}agent_class, {a}identity_confidence, {a}entry_page, {a}exit_page, {a}max_stage, {a}converted, "
    "{a}order_value, {a}terminal_blocker_id, {a}blocker_confidence, {a}diagnosis_method"
)


def session_cols(alias: str = "") -> str:
    return SESSION_COLUMNS.format(a=f"{alias}." if alias else "")


def one_row(cur: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None) -> tuple[Any, ...] | None:
    return db.one(cur, sql, params)
