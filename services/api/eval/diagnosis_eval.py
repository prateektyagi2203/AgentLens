"""Diagnosis evaluation against synthetic ground truth (SC4). Only the eval package may read ground truth (PRD 12.6).

Each synthetic session is mapped to the pipeline session of its last request. Population: synthetic agent sessions
(expected tier not human) that identification placed in diagnosis scope (verified/declared/suspected, not an excluded
class). Identification misses are reported separately (SC1-SC3 own those). Per blocker B01-B16:
TP = predicted == truth; FP = predicted blocker != truth (incl. truth none); FN = truth blocker not predicted.
B99 ("unknown") and no diagnosis both count as abstain: they are FNs when truth has a blocker and never FPs.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

from .. import settings
from .identification_eval import _session_map, load_ground_truth

BLOCKERS = [f"B{i:02d}" for i in range(1, 17)]
SC4_PRECISION_MIN = 0.85
SC4_RECALL_MIN = 0.80


@dataclass
class BlockerScore:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else None

    @property
    def support(self) -> int:
        return self.tp + self.fn


@dataclass
class DiagnosisEval:
    sessions_evaluated: int = 0
    excluded_identification_miss: int = 0
    unmatched_sessions: int = 0
    abstained: int = 0
    per_blocker: dict[str, BlockerScore] = field(default_factory=dict)
    confusion: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def tp(self) -> int:
        return sum(s.tp for s in self.per_blocker.values())

    @property
    def fp(self) -> int:
        return sum(s.fp for s in self.per_blocker.values())

    @property
    def fn(self) -> int:
        return sum(s.fn for s in self.per_blocker.values())

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def passed(self) -> bool:
        return self.precision >= SC4_PRECISION_MIN and self.recall >= SC4_RECALL_MIN

    def to_dict(self) -> dict[str, Any]:
        per = {
            b: asdict(s) | {"precision": s.precision, "recall": s.recall, "support": s.support}
            for b, s in sorted(self.per_blocker.items())
        }
        return {
            "sessions_evaluated": self.sessions_evaluated, "excluded_identification_miss": self.excluded_identification_miss,
            "unmatched_sessions": self.unmatched_sessions, "abstained": self.abstained, "precision": self.precision,
            "recall": self.recall, "passed": self.passed, "per_blocker": per, "confusion": self.confusion,
        }  # fmt: skip


def evaluate_diagnosis(con: duckdb.DuckDBPyConnection, logs: Path | None = None, run_id: str | None = None) -> DiagnosisEval:
    logs = logs or settings.logs_dir()
    gt_dir = logs.parent / "ground_truth" if logs.name == "logs" else None
    load_ground_truth(con, gt_dir, run_id)
    _session_map(con, logs)
    where = "WHERE g.run_id = ?" if run_id else ""
    rows = con.execute(
        f"""
        WITH last_req AS (
          SELECT m.sid, arg_max(r.session_id, r.ts) AS session_id FROM requests r JOIN _gt_map m USING (request_id) GROUP BY m.sid
        )
        SELECT g.synthetic_session_id, g.blocker_hit, s.session_id IS NOT NULL AS matched, s.identity_tier, s.agent_class,
               s.terminal_blocker_id, COALESCE(s.converted, false)
        FROM ground_truth g
        LEFT JOIN last_req l ON l.sid = g.synthetic_session_id
        LEFT JOIN sessions s ON s.session_id = l.session_id
        {where} {'AND' if where else 'WHERE'} g.expected_tier <> 'human'
        """,
        [run_id] if run_id else [],
    ).fetchall()
    cfg = settings.load_yaml("diagnosis")["scope"]
    tiers = set(cfg.get("tiers", ["verified", "declared", "suspected"]))
    excluded = set(cfg.get("excluded_classes", ["robots_token_only"]))
    ev = DiagnosisEval(per_blocker={b: BlockerScore() for b in BLOCKERS})
    for _sid, truth, matched, tier, agent_class, pred, converted in rows:
        if not matched:
            ev.unmatched_sessions += 1
            continue
        if tier not in tiers or agent_class in excluded:
            ev.excluded_identification_miss += 1
            continue
        ev.sessions_evaluated += 1
        truth = truth if truth in BLOCKERS else None
        pred = None if (converted or pred in (None, "B99")) else pred
        if pred is None and not converted:
            ev.abstained += 1
        ev.confusion.setdefault(truth or "none", {}).setdefault(pred or "abstain", 0)
        ev.confusion[truth or "none"][pred or "abstain"] += 1
        if pred is not None and pred == truth:
            ev.per_blocker[pred].tp += 1
        else:
            if pred is not None:
                ev.per_blocker[pred].fp += 1
            if truth is not None:
                ev.per_blocker[truth].fn += 1
    return ev


def format_diagnosis_report(ev: DiagnosisEval) -> str:
    def pct(v: float | None) -> str:
        return "  n/a" if v is None else f"{v * 100:5.1f}%"

    lines = [
        f"sessions evaluated: {ev.sessions_evaluated} (identification misses: {ev.excluded_identification_miss}, "
        f"unmatched: {ev.unmatched_sessions}, abstained: {ev.abstained})",
        "blocker  support    TP    FP    FN  precision  recall",
    ]
    for b, s in sorted(ev.per_blocker.items()):
        if s.tp or s.fp or s.fn:
            lines.append(f"{b:<7} {s.support:>8} {s.tp:>5} {s.fp:>5} {s.fn:>5}  {pct(s.precision):>9} {pct(s.recall):>7}")
    lines.append(
        f"SC4 overall: precision {ev.precision * 100:.1f}% (>= {SC4_PRECISION_MIN * 100:.0f}%), "
        f"recall {ev.recall * 100:.1f}% (>= {SC4_RECALL_MIN * 100:.0f}%) -> {'PASS' if ev.passed else 'FAIL'}"
    )
    lines.append("confusion (truth -> predicted):")
    for truth, preds in sorted(ev.confusion.items()):
        lines.append(f"  {truth}: {dict(sorted(preds.items()))}")
    return "\n".join(lines)


def write_report(ev: DiagnosisEval, out_dir: Path | None = None, label: str = "") -> Path:
    out_dir = out_dir or settings.data_dir() / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"diagnosis-eval{('-' + label) if label else ''}-{date.today().isoformat()}.md"
    path.write_text("```\n" + format_diagnosis_report(ev) + "\n```\n\n```json\n" + json.dumps(ev.to_dict(), indent=2) + "\n```\n", encoding="utf-8")
    return path
