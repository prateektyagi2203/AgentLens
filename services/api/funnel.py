"""C6 funnel (PRD 12): request -> page type / stage per config/funnel.yaml, session_stages, sessions.max_stage and
funnel aggregates (`funnel_stats`). Set-based DuckDB SQL, full recompute, idempotent.

A request reaches a stage when its method and path match the stage rule and its status is in `success_status`.
`session_stages` stores the stages a session literally reached (first timestamp). `max_stage` is the deepest stage
reached (an order forces S8), and the aggregates are cumulative (max_stage >= k) so a deep link never undercounts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import duckdb

from . import settings
from .ingest.pages import classify_path, load_rules, path_type_sql
from .pipeline import RunContext, register_step

AGENT_TIERS = ("verified", "declared", "suspected")
SEGMENT_TYPES = ("group", "tier", "agent_class", "agent", "operator")


@dataclass(frozen=True)
class StageRule:
    stage_id: str
    method: str
    path: str


def stage_rank(stage_id: str | None) -> int:
    """S1..S8 -> 1..8, anything else -> 0."""
    return int(stage_id[1:]) if stage_id and re.fullmatch(r"S\d+", stage_id) else 0


def load_stages(cfg: dict[str, Any] | None = None) -> list[tuple[str, str]]:
    cfg = cfg if cfg is not None else settings.load_yaml("funnel")
    return [(s["id"], s["name"]) for s in cfg.get("stages", [])]


def load_stage_rules(cfg: dict[str, Any] | None = None) -> list[StageRule]:
    cfg = cfg if cfg is not None else settings.load_yaml("funnel")
    return [
        StageRule(s["id"], str(r.get("method", "GET")).upper(), r["path"])
        for s in cfg.get("stages", [])
        for r in s.get("rules", [])
    ]


def classify_request(method: str, path: str, status: int | None, cfg: dict[str, Any] | None = None) -> tuple[str, str | None]:
    """(page_type, stage_id or None) for one request; mirrors the set-based SQL used by the pipeline."""
    cfg = cfg if cfg is not None else settings.load_yaml("funnel")
    page_type = classify_path(path, load_rules(cfg))
    if status not in set(cfg.get("success_status", [200, 201, 204, 302])):
        return page_type, None
    for rule in load_stage_rules(cfg):
        if rule.method == method.upper() and re.search(rule.path, path):
            return page_type, rule.stage_id
    return page_type, None


def stage_case_sql(rules: list[StageRule], method_col: str = "method", path_col: str = "path") -> str:
    def lit(s: str) -> str:
        return "'" + s.replace("'", "''") + "'"

    whens = " ".join(
        f"WHEN {method_col} = {lit(r.method)} AND regexp_matches({path_col}, {lit(r.path)}) THEN {lit(r.stage_id)}"
        for r in rules
    )
    return f"CASE {whens} ELSE NULL END"


def compute_funnel(con: duckdb.DuckDBPyConnection, ctx: RunContext | None = None) -> dict[str, int]:
    cfg = settings.load_yaml("funnel")
    stages = load_stages(cfg)
    rules = load_stage_rules(cfg)
    ok = ", ".join(str(int(s)) for s in cfg.get("success_status", [200, 201, 204, 302]))

    con.execute("CREATE OR REPLACE TEMP TABLE _stage_def (stage_id VARCHAR, rank INTEGER, name VARCHAR)")
    con.executemany("INSERT INTO _stage_def VALUES (?, ?, ?)", [(sid, stage_rank(sid), name) for sid, name in stages])

    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _req_stage AS
        SELECT session_id, stage_id, min(ts) AS ts
        FROM (
          SELECT session_id, ts, {stage_case_sql(rules)} AS stage_id
          FROM requests
          WHERE session_id IS NOT NULL AND NOT is_asset AND event_type = 'request' AND status IN ({ok})
        ) WHERE stage_id IS NOT NULL
        GROUP BY session_id, stage_id
        """
    )
    last = stages[-1][0] if stages else "S8"
    con.execute("DELETE FROM session_stages")
    con.execute(
        """
        INSERT INTO session_stages (session_id, stage_id, first_reached_ts)
        SELECT session_id, stage_id, ts FROM _req_stage
        UNION ALL
        SELECT s.session_id, ?, COALESCE(o.ts, s.end_ts)
        FROM sessions s LEFT JOIN orders o ON o.session_id = s.session_id
        WHERE s.converted AND NOT EXISTS (
          SELECT 1 FROM _req_stage r WHERE r.session_id = s.session_id AND r.stage_id = ?)
        """,
        [last, last],
    )
    con.execute(
        """
        UPDATE sessions SET max_stage = m.stage_id
        FROM (
          SELECT ss.session_id, arg_max(ss.stage_id, d.rank) AS stage_id
          FROM session_stages ss JOIN _stage_def d USING (stage_id) GROUP BY ss.session_id
        ) m WHERE sessions.session_id = m.session_id
        """
    )
    con.execute(
        "UPDATE sessions SET max_stage = NULL WHERE max_stage IS NOT NULL "
        "AND session_id NOT IN (SELECT session_id FROM session_stages)"
    )

    agents = ", ".join(f"'{t}'" for t in AGENT_TIERS)
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _fseg AS
        WITH base AS (
          SELECT session_id, identity_tier AS tier, agent_class, agent_name, operator,
                 CAST(start_ts AS DATE) AS day, COALESCE(CAST(substr(max_stage, 2) AS INTEGER), 0) AS mx
          FROM sessions WHERE COALESCE(identity_tier, 'human') <> 'internal'
        )
        SELECT 'group' AS segment_type, 'all' AS segment, day, mx FROM base
        UNION ALL SELECT 'group', 'agents', day, mx FROM base WHERE tier IN ({agents})
        UNION ALL SELECT 'group', 'human', day, mx FROM base WHERE COALESCE(tier, 'human') = 'human'
        UNION ALL SELECT 'tier', tier, day, mx FROM base WHERE tier IS NOT NULL
        UNION ALL SELECT 'agent_class', agent_class, day, mx FROM base WHERE agent_class IS NOT NULL
        UNION ALL SELECT 'agent', agent_name, day, mx FROM base WHERE agent_name IS NOT NULL AND agent_name <> 'unknown'
        UNION ALL SELECT 'operator', operator, day, mx FROM base WHERE operator IS NOT NULL AND operator <> 'unknown'
        """
    )
    con.execute("DELETE FROM funnel_stats")
    con.execute(
        """
        INSERT INTO funnel_stats
        WITH agg AS (
          SELECT g.segment_type, g.segment, g.day, d.stage_id, d.rank,
                 count(*) FILTER (WHERE g.mx >= d.rank) AS reached, count(*) AS total
          FROM _fseg g CROSS JOIN _stage_def d
          GROUP BY GROUPING SETS ((g.segment_type, g.segment, g.day, d.stage_id, d.rank),
                                  (g.segment_type, g.segment, d.stage_id, d.rank))
        ), prev AS (
          SELECT *, COALESCE(lag(reached) OVER (PARTITION BY segment_type, segment, day ORDER BY rank), total) AS prev_reached
          FROM agg
        )
        SELECT segment_type, segment, day, stage_id, CAST(reached AS INTEGER), CAST(total AS INTEGER),
               CASE WHEN prev_reached > 0 THEN reached::DOUBLE / prev_reached END,
               CASE WHEN total > 0 THEN reached::DOUBLE / total END,
               CAST(prev_reached - reached AS INTEGER)
        FROM prev
        """
    )
    n_stage = int(con.execute("SELECT count(*) FROM session_stages").fetchone()[0])  # type: ignore[index]
    n_stats = int(con.execute("SELECT count(*) FROM funnel_stats").fetchone()[0])  # type: ignore[index]
    n_max = int(con.execute("SELECT count(*) FROM sessions WHERE max_stage IS NOT NULL").fetchone()[0])  # type: ignore[index]
    return {"session_stages": n_stage, "sessions_with_stage": n_max, "funnel_stats": n_stats}


def funnel_table(
    con: duckdb.DuckDBPyConnection, segment_type: str = "group", segment: str = "agents", day: str | None = None
) -> list[dict[str, Any]]:
    """Stage rows (id, name, reached, step_conv, overall_conv, dropped) for one segment, for the drop-off table."""
    cond = "day IS NULL" if day is None else "day = CAST(? AS DATE)"
    params: list[Any] = [segment_type, segment] + ([] if day is None else [day])
    names = dict(load_stages())
    cur = con.execute(
        f"""
        SELECT stage_id, sessions_reached, sessions_total, step_conv, overall_conv, dropped
        FROM funnel_stats WHERE segment_type = ? AND segment = ? AND {cond}
        """,
        params,
    )
    cols = ["stage_id", "sessions_reached", "sessions_total", "step_conv", "overall_conv", "dropped"]
    rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
    rows.sort(key=lambda r: stage_rank(r["stage_id"]))
    for r in rows:
        r["name"] = names.get(r["stage_id"], r["stage_id"])
    return rows

def _step(con: duckdb.DuckDBPyConnection, ctx: RunContext) -> dict[str, int]:
    return compute_funnel(con, ctx)


register_step("funnel", _step, replace=True)

__all__ = [
    "classify_request", "compute_funnel", "funnel_table", "load_stage_rules", "load_stages", "path_type_sql",
    "stage_case_sql", "stage_rank",
]  # fmt: skip
