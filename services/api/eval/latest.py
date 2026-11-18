"""`agentlens eval`: run both evaluations against ground truth and write `<data>/eval/latest.json` (dashboard EvalResult).

The API serves that file as-is; it never touches ground truth itself.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from .. import settings
from .diagnosis_eval import evaluate_diagnosis
from .identification_eval import SC1_PRECISION_MIN, TIER_ORDER, evaluate_identification


def _ratio(num: float, den: float) -> float:
    return num / den if den else 0.0


def replay_stats(con: duckdb.DuckDBPyConnection) -> dict[str, float]:
    verdicts = []
    for (blob,) in con.execute("SELECT steps_json FROM replays WHERE status = 'completed'").fetchall():
        try:
            doc = json.loads(blob) if blob else {}
        except ValueError:
            doc = {}
        verdicts.append(doc.get("verdict") if isinstance(doc, dict) else None)
    return {"confirmation_rate": _ratio(verdicts.count("confirmed"), len(verdicts)), "completed": len(verdicts)}


def build_latest(con: duckdb.DuckDBPyConnection, logs: Path | None = None, run_id: str | None = None) -> dict[str, Any]:
    ident = evaluate_identification(con, logs, run_id)
    diag = evaluate_diagnosis(con, logs, run_id)
    cm = ident.confusion
    total = sum(sum(r) for r in cm)

    def prec(i: int) -> float:
        return _ratio(cm[i][i], sum(r[i] for r in cm))

    def rec(i: int) -> float:
        return _ratio(cm[i][i], sum(cm[i]))

    diagnosed = diag.tp + diag.fp
    sessions = con.execute("SELECT count(*) FROM sessions").fetchone()[0]  # type: ignore[index]
    now = datetime.now(UTC)
    per_blocker = []
    for bid, s in sorted(diag.per_blocker.items()):
        if s.support or s.fp:
            p, r = s.precision or 0.0, s.recall or 0.0
            per_blocker.append({"blocker_id": bid, "precision": p, "recall": r, "f1": _ratio(2 * p * r, p + r), "support": s.support})
    notes = [
        f"Identification: {ident.sessions_evaluated} synthetic sessions evaluated ({ident.unmatched_sessions} unmatched).",
        f"Verified precision target {SC1_PRECISION_MIN:.0%}; identification checks {'pass' if ident.passed else 'do not all pass'}.",
        f"Diagnosis: {diag.sessions_evaluated} agent sessions in scope; precision {diag.precision:.1%}, recall {diag.recall:.1%} "
        f"({'meets' if diag.passed else 'below'} the SC4 targets).",
        "Impact error is not evaluated: the synthetic generator has no counterfactual revenue.",
        "Ground truth is synthetic; real traffic will score lower, especially for the Suspected tier.",
    ]
    return {
        "run_id": f"eval-{now:%Y%m%d%H%M%S}", "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dataset": f"{settings.data_dir().name}: {sessions:,} sessions (synthetic)",
        "identification": {
            "tier_accuracy": _ratio(sum(cm[i][i] for i in range(len(TIER_ORDER))), total),
            "verified_precision": prec(0), "verified_recall": rec(0), "declared_precision": prec(1), "declared_recall": rec(1),
            "suspected_precision": prec(2), "suspected_recall": rec(2), "confusion": cm,
        },
        "diagnosis": {
            "top1_accuracy": diag.recall, "coverage": _ratio(diagnosed, diagnosed + diag.abstained), "per_blocker": per_blocker,
        },
        "impact": {"mean_abs_pct_error": None},
        "replay": replay_stats(con),
        "notes": notes,
    }  # fmt: skip


def write_latest(doc: dict[str, Any]) -> Path:
    path = settings.data_dir() / "eval" / "latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return path
