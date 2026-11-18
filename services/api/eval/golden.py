"""The 2,000-session golden set for SC4, generated deterministically from the synth scenario (no files to check in).

Five segments, each its own seed, start date and friction toggle set, with agent-heavy persona shares so every blocker has
dozens of ground-truth cases. The in-process fake store (`fakestore`) answers the site checks for each segment's toggles at
the segment's start, so one diagnose run reads the right snapshot for every session (checks are valid from one run to the next).

    agentlens eval-diagnosis --golden        # generate (cached under <data>/golden), run the pipeline, score

Same code + seeds => byte-identical logs, so the set is reproducible; `tests/python/test_eval_diagnosis.py` regenerates it and
asserts the SC4 thresholds.
"""

from __future__ import annotations

import copy
import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .. import db, pipeline, settings
from ..diagnosis.sitechecks import run_site_checks
from ..synth.config import SynthConfig
from ..synth.offline import run_offline
from .diagnosis_eval import DiagnosisEval, evaluate_diagnosis
from .fakestore import store_transport

AGENT_SHARES = {
    "human": 0.20, "signed_agent": 0.22, "headless_agent": 0.18, "chatgpt_fetcher": 0.12, "claude_fetcher": 0.07,
    "perplexity_fetcher": 0.06, "forged_signature_bot": 0.02, "crawler": 0.04,
}  # fmt: skip


@dataclass(frozen=True)
class Segment:
    name: str
    toggles: frozenset[str]
    sessions: int
    seed: int
    start_date: str
    noise: dict[str, float] = field(default_factory=dict)
    shares: dict[str, float] | None = None


STRESS_SHARES = {"human": 0.05, "signed_agent": 0.35, "headless_agent": 0.30, "crawler": 0.20, "forged_signature_bot": 0.05,
                 "chatgpt_fetcher": 0.05}  # fmt: skip

SHOPPER_SHARES = {"signed_agent": 0.55, "headless_agent": 0.45}

SEGMENTS = [
    Segment("clean", frozenset(), 100, 4101, "2026-11-01"),
    Segment("before", frozenset({"F03", "F05", "F06", "F07", "F09", "F10"}), 250, 4102, "2026-11-04"),
    Segment("checkout", frozenset({"F02", "F16", "F08", "F04"}), 300, 4103, "2026-11-07"),
    Segment("infra", frozenset({"F01", "F13", "F14", "F05", "F09"}), 250, 4104, "2026-11-10", {"p_broken_link": 0.08}),
    Segment("ratelimit", frozenset({"F12", "F03", "F06"}), 250, 4105, "2026-11-13", {"p_broken_link": 0.04}),
    Segment("pricing", frozenset({"F12"}), 200, 4106, "2026-11-16", {}, STRESS_SHARES),
    Segment("payments", frozenset({"F10"}), 200, 4107, "2026-11-19", {}, STRESS_SHARES),
    Segment("cod", frozenset({"F15", "F11"}), 450, 4108, "2026-11-22", {}, SHOPPER_SHARES),
]
TOTAL_SESSIONS = sum(s.sessions for s in SEGMENTS)
THRESHOLDS = {"precision": 0.85, "recall": 0.80}


def _config(seg: Segment) -> SynthConfig:
    cfg = SynthConfig.load()
    personas = copy.deepcopy(cfg.raw["personas"])
    shares = seg.shares or AGENT_SHARES
    for name, share in shares.items():
        if name in personas:
            personas[name]["share"] = share
    for name in personas:
        if name not in shares:
            personas[name]["share"] = 0.0
    noise = {**cfg.raw["noise"], **seg.noise}
    return SynthConfig({**cfg.raw, "personas": personas, "noise": noise})


@contextmanager
def _env(data_dir: Path) -> Iterator[None]:
    saved = {k: os.environ.get(k) for k in ("AGENTLENS_DATA_DIR", "AGENTLENS_DB_PATH", "AGENTLENS_SITE_URL")}
    os.environ["AGENTLENS_DATA_DIR"] = str(data_dir)
    os.environ.pop("AGENTLENS_DB_PATH", None)
    os.environ.pop("AGENTLENS_SITE_URL", None)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def generate(data_dir: Path) -> dict[str, int]:
    """Write merged logs, orders and ground truth for all segments under `data_dir`. Returns request/session counts."""
    work = data_dir / "_seg"
    logs, gt = data_dir / "logs", data_dir / "ground_truth"
    for d in (logs, gt, work):
        shutil.rmtree(d, ignore_errors=True)
    logs.mkdir(parents=True)
    gt.mkdir(parents=True)
    lines = 0
    with (data_dir / "orders.jsonl").open("w", encoding="utf-8") as orders:
        for seg in SEGMENTS:
            out = work / seg.name / "logs"
            res = run_offline(sessions=seg.sessions, days=2, seed=seg.seed, out=out, start_date=seg.start_date, toggles=set(seg.toggles),
                              run_id=f"golden-{seg.name}", force=True, cfg=_config(seg))  # fmt: skip
            lines += res.lines
            for f in res.files:
                shutil.move(str(f), logs / f.name)
            shutil.move(str(res.ground_truth), gt / res.ground_truth.name)
            orders.write((work / seg.name / "orders.jsonl").read_text(encoding="utf-8"))
    shutil.rmtree(work, ignore_errors=True)
    return {"sessions": TOTAL_SESSIONS, "lines": lines}


def run_golden(data_dir: Path | None = None, *, regenerate: bool = False) -> DiagnosisEval:
    """Generate (if needed), run ingest..sessionize/funnel, probe the fake store per segment, diagnose, score."""
    data_dir = data_dir or settings.data_dir() / "golden"
    with _env(data_dir):
        if regenerate or not (data_dir / "logs").exists():
            generate(data_dir)
        db_file = data_dir / "agentlens.duckdb"
        if db_file.exists():
            db_file.unlink()
        con = db.connect(db_file)
        try:
            pipeline.run_steps(con, ["ingest", "identify", "sessionize", "funnel"], {"source": str(data_dir / "logs"), "fmt": "jsonl"})
            for seg in SEGMENTS:
                start = datetime.fromisoformat(seg.start_date).replace(tzinfo=UTC) - timedelta(hours=1)
                run_site_checks(con, "http://store.test", transport=store_transport(set(seg.toggles)), now=start)
            res = pipeline.run_steps(con, ["diagnose"], {"skip_site_probe": True, "llm_provider": "off"})
            if not res.ok:
                raise RuntimeError(f"diagnose failed: {res.steps}")
            return evaluate_diagnosis(con, data_dir / "logs")
        finally:
            con.close()
