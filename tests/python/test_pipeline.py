"""Pipeline step registry: ordering, replace semantics, rollback on failure, runs row."""

from __future__ import annotations

import json

import pytest
from agentlens import db, pipeline
from helpers import human_visit, write_jsonl


@pytest.fixture
def env(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    write_jsonl(logs / "access-2026-11-01.jsonl", human_visit(0, "ck1"))
    c = db.connect(":memory:")
    yield c, logs
    for name in ("funnel", "zz_fail", "zz_extra"):
        pipeline.unregister_step(name)
    c.close()


def test_registered_steps_run_in_canonical_order(env):
    con, logs = env
    order: list[str] = []
    pipeline.register_step("zz_extra", lambda c, ctx: order.append("zz_extra") or {"n": 1})
    pipeline.register_step("funnel", lambda c, ctx: order.append("funnel") or {"n": 2})
    res = pipeline.run_all(con, source=logs)
    assert res.ok and [s["name"] for s in res.steps] == ["ingest", "identify", "sessionize", "funnel", "zz_extra"]
    assert order == ["funnel", "zz_extra"]
    row = con.execute("SELECT status, steps_json, counts_json, finished_at FROM runs").fetchall()[0]
    assert row[0] == "success" and row[3] is not None
    assert json.loads(row[2])["funnel"] == {"n": 2} and json.loads(row[2])["ingest"]["requests_inserted"] > 0


def test_duplicate_registration_needs_replace():
    pipeline.register_step("funnel", lambda c, ctx: None)
    try:
        with pytest.raises(ValueError):
            pipeline.register_step("funnel", lambda c, ctx: None)
        pipeline.register_step("funnel", lambda c, ctx: {"v": 2}, replace=True)
    finally:
        pipeline.unregister_step("funnel")


def test_failure_rolls_back_step_and_keeps_earlier_outputs(env):
    con, logs = env

    def bad(c, ctx):
        c.execute("DELETE FROM sessions")
        raise RuntimeError("boom")

    pipeline.run_all(con, source=logs)
    before = con.execute("SELECT count(*) FROM sessions").fetchall()[0][0]
    assert before > 0
    pipeline.register_step("zz_fail", bad)
    res = pipeline.run_all(con, source=logs)
    assert not res.ok and res.status == "failed" and res.steps[-1]["name"] == "zz_fail"
    assert "boom" in res.steps[-1]["error"]
    assert con.execute("SELECT count(*) FROM sessions").fetchall()[0][0] == before
    assert con.execute("SELECT status FROM runs ORDER BY started_at DESC LIMIT 1").fetchall()[0][0] == "failed"


def test_rerun_is_idempotent(env):
    con, logs = env
    pipeline.run_all(con, source=logs)
    snap = [con.execute(f"SELECT count(*) FROM {t}").fetchall()[0][0] for t in ("requests", "sessions")]
    pipeline.run_all(con, source=logs)
    assert [con.execute(f"SELECT count(*) FROM {t}").fetchall()[0][0] for t in ("requests", "sessions")] == snap


def test_unknown_step_name_rejected(env):
    with pytest.raises(KeyError):
        pipeline.run_steps(env[0], names=["nope"])
