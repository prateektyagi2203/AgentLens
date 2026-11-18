"""C10 recommendation engine (PRD 15): one ranked fix per priced blocker, from the catalog in config/blockers.yaml.

priority_score = risk_base / effort_weight (S=1, M=2, L=4), highest first. `rec_id` is `rec-<blocker>` so re-runs update in
place and keep the user's `status` / `fixed_annotation_id`; recommendations for blockers that are no longer priced are
removed unless already marked fixed. `body` is JSON (what / why / how to verify / evidence / optional LLM explanation).
"""

from __future__ import annotations

import json
import os
from typing import Any

import duckdb

from . import settings
from .diagnosis.llm import get_provider
from .impact import load_config as impact_config
from .pipeline import RunContext, register_step


def load_blockers() -> dict[str, dict[str, Any]]:
    return dict(settings.load_yaml("blockers")["blockers"])


def priority(risk_base: float, effort: str, weights: dict[str, float]) -> float:
    return risk_base / float(weights.get(effort, weights.get("M", 2)))


def _template_explanation(name: str, n: int, pct: float, pattern: str | None, risk: float) -> str:
    cited = f"Typical failing call: {pattern}." if pattern else ""
    return (f"{pct:.0f}% of failed agent sessions ({n}) ended on {name.lower()}. {cited} "
            f"Fixing it could recover about ₹{risk:,.0f} a month.").replace("  ", " ")  # fmt: skip


def build_recommendations(con: duckdb.DuckDBPyConnection, ctx: RunContext | None = None) -> dict[str, Any]:
    catalog = load_blockers()
    weights = {k: float(v) for k, v in impact_config().get("effort_weights", {"S": 1, "M": 2, "L": 4}).items()}
    run_id = ctx.run_id if ctx else "manual"
    llm_name = (ctx.params.get("llm_provider") if ctx else None) or os.getenv("AGENTLENS_LLM_PROVIDER") or "mock"
    provider = None if llm_name.lower() in ("off", "none", "rules") else get_provider(llm_name)

    rows = con.execute(
        """
        SELECT i.blocker_id, i.sessions_blocked, i.risk_base, i.risk_low, i.risk_high,
               (SELECT count(*) FROM sessions WHERE terminal_blocker_id IS NOT NULL) AS failed,
               (SELECT mode(regexp_replace(json_extract_string(h.evidence_json, '$[0].summary'), '[?].*| \\(.*\\)$', ''))
                  FROM blocker_hits h WHERE h.blocker_id = i.blocker_id AND h.is_terminal) AS pattern
        FROM impact i WHERE i.risk_base > 0
        """
    ).fetchall()
    keep: list[str] = []
    out: list[tuple[Any, ...]] = []
    for blocker_id, n, risk_base, risk_low, risk_high, failed, pattern in rows:
        meta = catalog.get(blocker_id)
        if meta is None:
            continue
        effort = str(meta.get("effort", "M"))
        pct = 100.0 * n / failed if failed else 0.0
        explanation = None
        if provider is not None:
            ev = f"{n} sessions ({pct:.0f}% of failed agent sessions), typical failing call {pattern}"
            explanation = provider.explain(blocker_id, meta["name"], ev) or _template_explanation(meta["name"], n, pct, pattern, risk_base)
        body = {
            "what": meta["fix"], "why_it_helps": meta["description"], "how_to_verify": meta["how_to_verify"],
            "verify_metric": f"Agent sessions ending with {blocker_id} per day",
            "evidence_summary": f"{n} agent sessions, {pct:.0f}% of failed agent sessions" + (f"; typical: {pattern}" if pattern else ""),
            "llm_explanation": explanation, "risk_inr_base": risk_base, "risk_inr_low": risk_low, "risk_inr_high": risk_high,
            "sessions_blocked": n, "stage": meta.get("stage"),
        }  # fmt: skip
        rec_id = f"rec-{blocker_id}"
        keep.append(rec_id)
        out.append((rec_id, run_id, blocker_id, f"{meta['name']}: {meta['fix']}".split(". ")[0][:140], json.dumps(body), effort,
                    str(meta.get("owner", "")), priority(risk_base, effort, weights)))  # fmt: skip
    con.execute("DELETE FROM recommendations WHERE fixed_annotation_id IS NULL AND status IS DISTINCT FROM 'fixed' AND rec_id NOT IN (SELECT unnest(?))", [keep or [""]])  # fmt: skip
    for rec_id, rid, bid, title, body_json, effort, owner, score in out:
        con.execute(
            """
            INSERT INTO recommendations (rec_id, run_id, blocker_id, title, body, effort, owner, priority_score, status, fixed_annotation_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', NULL)
            ON CONFLICT (rec_id) DO UPDATE SET run_id = excluded.run_id, blocker_id = excluded.blocker_id, title = excluded.title,
              body = excluded.body, effort = excluded.effort, owner = excluded.owner, priority_score = excluded.priority_score
            """,
            [rec_id, rid, bid, title, body_json, effort, owner, score],
        )
    return {"recommendations": len(out), "llm": provider.name if provider else "off"}


def _step(con: duckdb.DuckDBPyConnection, ctx: RunContext) -> dict[str, Any]:
    return build_recommendations(con, ctx)


register_step("recommend", _step, replace=True)
