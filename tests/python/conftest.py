"""Shared fixtures: a small synthetic store taken through the whole M3 chain."""

from __future__ import annotations

from pathlib import Path

import pytest
from agentlens import db, pipeline
from agentlens.synth.offline import run_offline

BEFORE_TOGGLES = {"F03", "F05", "F06", "F07", "F09", "F10"}
CHAIN_PARAMS = {"skip_site_probe": True, "llm_provider": "off"}


@pytest.fixture(scope="session")
def synth_logs(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("m3-synth")
    run_offline(sessions=1500, days=4, seed=11, out=base / "logs", toggles=set(BEFORE_TOGGLES), run_id="m3", force=True)
    return base / "logs"


@pytest.fixture(scope="session")
def chain_db(synth_logs: Path, tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    """DuckDB with every step run once (`run-all` equivalent). Read-only for tests."""
    con = db.connect(tmp_path_factory.mktemp("m3-db") / "agentlens.duckdb")
    res = pipeline.run_steps(con, None, {"source": str(synth_logs), "fmt": "jsonl", **CHAIN_PARAMS})
    assert res.ok, res.steps
    yield con
    con.close()
