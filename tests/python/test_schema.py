from agentlens import db


def test_schema_applies_and_is_idempotent():
    con = db.connect(":memory:")
    con.execute(db.SCHEMA_PATH.read_text(encoding="utf-8"))
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    assert {"requests", "sessions", "blocker_hits", "impact", "ground_truth", "runs"} <= tables
