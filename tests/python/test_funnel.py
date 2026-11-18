"""C5 funnel: request classification, session stages, max_stage, aggregates."""

from __future__ import annotations

import pytest
from agentlens import db, pipeline
from agentlens.funnel import classify_request, funnel_table, stage_rank
from helpers import rec, write_jsonl

UA = "Mozilla/5.0 (compatible; ChatGPT-User/1.0)"


@pytest.mark.parametrize(
    ("method", "path", "status", "expected"),
    [
        ("GET", "/", 200, ("home", "S1")),
        ("GET", "/search?q=x".split("?")[0], 200, ("search", "S1")),
        ("GET", "/c/sneakers", 200, ("plp", "S1")),
        ("GET", "/p/white-sneaker", 200, ("pdp", "S2")),
        ("GET", "/api/products/p1/variants", 200, ("variant_api", "S3")),
        ("GET", "/api/serviceability", 200, ("serviceability_api", "S4")),
        ("POST", "/api/cart", 201, ("cart_api", "S5")),
        ("GET", "/checkout", 200, ("checkout", "S6")),
        ("POST", "/api/checkout", 201, ("checkout_api", "S7")),
        ("GET", "/order/confirmed/o1", 200, ("order_confirm", "S8")),
        ("POST", "/api/cart", 409, ("cart_api", None)),  # a failed call does not reach the stage
        ("GET", "/p/gone", 404, ("pdp", None)),
        ("GET", "/api/cart", 200, ("cart_api", None)),  # wrong verb for S5
        ("GET", "/robots.txt", 200, ("robots", None)),
        ("GET", "/_next/static/app.js", 200, ("asset", None)),
    ],
)
def test_classify_request(method, path, status, expected):
    assert classify_request(method, path, status) == expected


def test_stage_rank():
    assert [stage_rank(s) for s in ("S1", "S8", None, "x")] == [1, 8, 0, 0]


def _session(tmp_path, name, steps, *, ip):
    records = [
        rec(i * 5, path=p, method=m, status=s, user_agent=UA, ip_hash=ip, accept="*/*", sec_fetch_mode=None,
            sec_fetch_dest=None, sec_fetch_site=None)
        for i, (m, p, s) in enumerate(steps)
    ]  # fmt: skip
    write_jsonl(tmp_path / f"{name}.jsonl", records)


def test_max_stage_stage_rows_and_dropoff(tmp_path):
    _session(tmp_path, "a", [("GET", "/", 200), ("GET", "/p/x", 200), ("POST", "/api/cart", 201)], ip="ip-a")
    _session(tmp_path, "b", [("GET", "/", 200), ("GET", "/p/x", 200)], ip="ip-b")
    _session(tmp_path, "c", [("GET", "/", 200)], ip="ip-c")
    _session(tmp_path, "d", [("GET", "/p/x", 404)], ip="ip-d")
    con = db.connect(":memory:")
    assert pipeline.run_steps(con, ["ingest", "identify", "sessionize", "funnel"], {"source": str(tmp_path), "fmt": "jsonl"}).ok
    got = dict(con.execute("SELECT r.ip_hash, any_value(s.max_stage) FROM sessions s JOIN requests r USING (session_id) GROUP BY 1 ORDER BY 1").fetchall())
    assert got == {"ip-a": "S5", "ip-b": "S2", "ip-c": "S1", "ip-d": None}
    stages = con.execute(
        "SELECT DISTINCT ss.stage_id FROM session_stages ss JOIN requests r USING (session_id) WHERE r.ip_hash = 'ip-a' ORDER BY 1"
    ).fetchall()
    assert [r[0] for r in stages] == ["S1", "S2", "S5"]

    rows = {r["stage_id"]: r for r in funnel_table(con, "group", "agents")}
    assert [rows[s]["sessions_reached"] for s in ("S1", "S2", "S5")] == [3, 2, 1]
    assert rows["S1"]["sessions_total"] == 4 and rows["S2"]["dropped"] == 1 and rows["S5"]["dropped"] == 0
    assert rows["S2"]["step_conv"] == pytest.approx(2 / 3) and rows["S5"]["overall_conv"] == pytest.approx(1 / 4)
    assert rows["S5"]["name"]


def test_funnel_is_idempotent(tmp_path):
    _session(tmp_path, "a", [("GET", "/", 200), ("GET", "/p/x", 200)], ip="ip-a")
    con = db.connect(":memory:")
    pipeline.run_steps(con, ["ingest", "identify", "sessionize", "funnel"], {"source": str(tmp_path), "fmt": "jsonl"})
    first = con.execute("SELECT count(*) FROM funnel_stats").fetchone()
    pipeline.run_steps(con, ["funnel"])
    assert con.execute("SELECT count(*) FROM funnel_stats").fetchone() == first
    assert con.execute("SELECT count(*) FROM session_stages").fetchone()[0] == 2


def test_converted_session_reaches_s8(chain_db):
    bad = chain_db.execute(
        "SELECT count(*) FROM sessions WHERE converted AND (max_stage IS DISTINCT FROM 'S8')"
    ).fetchone()[0]
    assert bad == 0
    assert chain_db.execute("SELECT count(*) FROM sessions WHERE converted").fetchone()[0] > 0
