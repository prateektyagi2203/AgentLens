"""End to end: synth offline -> run-all -> eval-identification (SC1-SC3)."""

from __future__ import annotations

import pytest
from agentlens import db, pipeline
from agentlens.eval import evaluate_identification
from agentlens.synth import offline

SESSIONS = 3000


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("integration")
    res = offline.run_offline(sessions=SESSIONS, days=7, seed=11, out=root / "logs", run_id="int")
    con = db.connect(":memory:")
    run = pipeline.run_all(con, source=root / "logs")
    ev = evaluate_identification(con, root / "logs", "int")
    yield res, con, run, ev
    con.close()


def test_run_all_succeeds_and_populates_tables(world):
    res, con, run, _ = world
    assert run.ok, run.steps
    n = lambda t: con.execute(f"SELECT count(*) FROM {t}").fetchall()[0][0]  # noqa: E731
    assert n("requests") > 0.95 * (res.lines - res.orders)
    assert n("sessions") >= SESSIONS * 0.95
    assert n("orders") > 0 and n("ingest_errors") == 0 and n("request_signatures") > 0
    assert con.execute("SELECT count(*) FROM requests WHERE session_id IS NULL AND identity_tier <> 'internal'").fetchall()[0][0] == 0
    tiers = {r[0] for r in con.execute("SELECT DISTINCT identity_tier FROM requests").fetchall()}
    assert {"verified", "declared", "suspected", "human"} <= tiers


def test_orders_link_to_sessions_and_humans_convert_a_few_percent(world):
    _, con, _, _ = world
    linked, total = con.execute("SELECT count(*) FILTER (WHERE session_id IS NOT NULL), count(*) FROM orders").fetchall()[0]
    assert total > 0 and linked / total > 0.95
    rate = con.execute(
        "SELECT avg(CASE WHEN converted THEN 1.0 ELSE 0.0 END) FROM sessions WHERE identity_tier = 'human'"
    ).fetchall()[0][0]
    assert 0.015 <= rate <= 0.06


def test_sc1_no_false_verified_and_full_precision(world):
    ev = world[3]
    assert ev.false_verified == 0 and ev.forged_marked_verified == 0
    assert ev.verified_precision == 1.0 and ev.sc1


def test_sc2_declared_accuracy(world):
    ev = world[3]
    assert ev.declared_sessions > 100 and ev.declared_accuracy is not None and ev.declared_accuracy >= 0.98 and ev.sc2


def test_sc3_suspected_recall_at_low_fpr(world):
    ev = world[3]
    assert ev.suspected_recall is not None and ev.suspected_recall >= 0.75
    assert ev.human_fpr is not None and ev.human_fpr <= 0.05 and ev.sc3
    print(f"\nSC1 fv={ev.false_verified} prec={ev.verified_precision} | SC2 acc={ev.declared_accuracy:.3f} "
          f"| SC3 recall={ev.suspected_recall:.3f} fpr={ev.human_fpr:.4f}")  # fmt: skip
