"""Identification evaluation against synthetic ground truth (SC1-SC3). The ONLY module allowed to read ground truth.

It re-reads the raw log files to map `request_id` to the generator's session link, because ingestion deliberately drops it
(PRD 12.6). Metrics are computed per synthetic session using the strongest identity among that session's requests.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import duckdb

from .. import settings

RANK_SQL = "CASE identity_tier WHEN 'internal' THEN 5 WHEN 'verified' THEN 4 WHEN 'declared' THEN 3 WHEN 'suspected' THEN 2 ELSE 1 END"

SC1_FALSE_VERIFIED_MAX = 0
SC1_PRECISION_MIN = 1.0
SC2_DECLARED_ACCURACY_MIN = 0.98
SC3_RECALL_MIN = 0.75
SC3_FPR_MAX = 0.05


@dataclass
class IdentificationEval:
    sessions_evaluated: int = 0
    unmatched_sessions: int = 0
    false_verified: int = 0
    verified_precision: float | None = None
    verified_recall: float | None = None
    declared_accuracy: float | None = None
    declared_sessions: int = 0
    suspected_recall: float | None = None
    suspected_sessions: int = 0
    human_fpr: float | None = None
    human_sessions: int = 0
    forged_marked_verified: int = 0
    per_persona: dict[str, dict[str, int]] = field(default_factory=dict)
    sc1: bool = False
    sc2: bool = False
    sc3: bool = False

    @property
    def passed(self) -> bool:
        return self.sc1 and self.sc2 and self.sc3

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"passed": self.passed}


def load_ground_truth(con: duckdb.DuckDBPyConnection, gt_dir: Path | None = None, run_id: str | None = None) -> int:
    gt_dir = gt_dir or settings.data_dir() / "ground_truth"
    files = sorted(gt_dir.glob(f"gt-{run_id}.jsonl" if run_id else "gt-*.jsonl"))
    rows: list[tuple[Any, ...]] = []
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            g = json.loads(line)
            rows.append((g["run_id"], g["synthetic_session_id"], g["persona"], g["expected_tier"], g.get("operator"),
                         g.get("agent_class"), g.get("task"), json.dumps(g.get("toggles_active", [])), g.get("blocker_hit"),
                         g.get("stage_of_failure"), bool(g.get("converted"))))  # fmt: skip
    if not rows:
        return 0
    run_ids = sorted({r[0] for r in rows})
    con.execute("DELETE FROM ground_truth WHERE run_id IN (SELECT unnest(?))", [run_ids])
    con.executemany("INSERT INTO ground_truth VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def _session_map(con: duckdb.DuckDBPyConnection, logs: Path) -> None:
    pattern = logs.as_posix() if logs.is_file() else (logs / "*.jsonl").as_posix()
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE _gt_map AS
        SELECT request_id, meta.synth_session_id AS sid
        FROM read_ndjson(?, columns = {request_id: 'VARCHAR', meta: 'STRUCT(synth_session_id VARCHAR)'},
                         ignore_errors = true)
        WHERE meta.synth_session_id IS NOT NULL
        """,
        [pattern],
    )


def evaluate_identification(con: duckdb.DuckDBPyConnection, logs: Path | None = None,
                            run_id: str | None = None) -> IdentificationEval:  # fmt: skip
    logs = logs or settings.logs_dir()
    gt_dir = logs.parent / "ground_truth" if logs.name == "logs" else None
    load_ground_truth(con, gt_dir, run_id)
    _session_map(con, logs)
    where = "WHERE g.run_id = ?" if run_id else ""
    params = [run_id] if run_id else []
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _gt_eval AS
        WITH per AS (
          SELECT m.sid,
                 arg_max(r.identity_tier, {RANK_SQL.replace('identity_tier', 'r.identity_tier')}) AS tier,
                 arg_max(r.operator, {RANK_SQL.replace('identity_tier', 'r.identity_tier')}) AS operator,
                 arg_max(r.agent_name, {RANK_SQL.replace('identity_tier', 'r.identity_tier')}) AS agent_name,
                 bool_or(r.signature_status = 'valid') AS any_valid
          FROM requests r JOIN _gt_map m USING (request_id)
          GROUP BY m.sid
        )
        SELECT g.synthetic_session_id AS sid, g.persona, g.expected_tier, g.operator AS exp_operator,
               p.tier, p.operator, p.agent_name, p.any_valid
        FROM ground_truth g LEFT JOIN per p ON p.sid = g.synthetic_session_id
        {where}
        """,
        params,
    )
    rows = con.execute("SELECT persona, expected_tier, exp_operator, tier, operator FROM _gt_eval").fetchall()
    ev = IdentificationEval()
    ver_tp = ver_fp = ver_expected = 0
    declared_ok = declared_total = 0
    susp_ok = susp_total = 0
    human_flagged = human_total = 0
    for persona, expected, exp_op, tier, op in rows:
        if tier is None:
            ev.unmatched_sessions += 1
            continue
        ev.sessions_evaluated += 1
        bucket = ev.per_persona.setdefault(persona, {})
        bucket[tier] = bucket.get(tier, 0) + 1
        if tier == "verified":
            if expected == "verified":
                ver_tp += 1
            else:
                ver_fp += 1
                if persona == "forged_signature_bot":
                    ev.forged_marked_verified += 1
        if expected == "verified":
            ver_expected += 1
        elif expected == "declared":
            declared_total += 1
            declared_ok += int(tier == "declared" and (exp_op is None or op == exp_op))
        elif expected == "suspected":
            susp_total += 1
            susp_ok += int(tier == "suspected")
        elif expected == "human":
            human_total += 1
            human_flagged += int(tier in ("suspected", "declared", "verified"))
    ev.false_verified = ver_fp
    ev.verified_precision = ver_tp / (ver_tp + ver_fp) if (ver_tp + ver_fp) else None
    ev.verified_recall = ver_tp / ver_expected if ver_expected else None
    ev.declared_sessions, ev.suspected_sessions, ev.human_sessions = declared_total, susp_total, human_total
    ev.declared_accuracy = declared_ok / declared_total if declared_total else None
    ev.suspected_recall = susp_ok / susp_total if susp_total else None
    ev.human_fpr = human_flagged / human_total if human_total else None
    ev.sc1 = ev.false_verified <= SC1_FALSE_VERIFIED_MAX and (ev.verified_precision or 0) >= SC1_PRECISION_MIN
    ev.sc2 = (ev.declared_accuracy or 0) >= SC2_DECLARED_ACCURACY_MIN
    ev.sc3 = (ev.suspected_recall or 0) >= SC3_RECALL_MIN and (ev.human_fpr if ev.human_fpr is not None else 1) <= SC3_FPR_MAX
    return ev


def format_report(ev: IdentificationEval) -> str:
    def pct(v: float | None) -> str:
        return "n/a" if v is None else f"{v * 100:.1f}%"

    lines = [
        f"sessions evaluated: {ev.sessions_evaluated} (unmatched: {ev.unmatched_sessions})",
        f"SC1 verified: false_verified={ev.false_verified} precision={pct(ev.verified_precision)} "
        f"recall={pct(ev.verified_recall)} forged_marked_verified={ev.forged_marked_verified} -> {'PASS' if ev.sc1 else 'FAIL'}",
        f"SC2 declared accuracy: {pct(ev.declared_accuracy)} over {ev.declared_sessions} sessions "
        f"(target >= {SC2_DECLARED_ACCURACY_MIN * 100:.0f}%) -> {'PASS' if ev.sc2 else 'FAIL'}",
        f"SC3 suspected recall: {pct(ev.suspected_recall)} over {ev.suspected_sessions} sessions "
        f"(target >= {SC3_RECALL_MIN * 100:.0f}%), human FPR {pct(ev.human_fpr)} over {ev.human_sessions} "
        f"(target <= {SC3_FPR_MAX * 100:.0f}%) -> {'PASS' if ev.sc3 else 'FAIL'}",
        "per persona (identified tier counts):",
    ]
    for persona, counts in sorted(ev.per_persona.items()):
        lines.append(f"  {persona}: {dict(sorted(counts.items()))}")
    return "\n".join(lines)
