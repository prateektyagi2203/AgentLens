"""C5 sessionization: keys, timeouts, identity inheritance, order linkage."""

from __future__ import annotations

import json

import pytest
from agentlens import db
from agentlens.identify.engine import identify
from agentlens.ingest import ingest_path
from agentlens.sessions import sessionize
from helpers import rec, write_jsonl

GPT_UA = "Mozilla/5.0 (compatible; ChatGPT-User/1.0)"


def run(tmp_path, records, orders=None):
    con = db.connect(":memory:")
    logs = tmp_path / "logs"
    logs.mkdir(exist_ok=True)
    write_jsonl(logs / "access-2026-11-01.jsonl", records)
    if orders:
        (tmp_path / "orders.jsonl").write_text("\n".join(json.dumps(o) for o in orders) + "\n", encoding="utf-8")
    ingest_path(con, logs)
    identify(con)
    sessionize(con)
    return con


def sessions(con):
    return con.execute(
        "SELECT session_id, request_count, page_count, has_beacon, identity_tier, entry_page, exit_page, "
        "converted, order_value FROM sessions ORDER BY start_ts"
    ).fetchall()


@pytest.mark.parametrize(("gap_min", "expected"), [(29, 1), (31, 2)])
def test_human_timeout_is_30_minutes(tmp_path, gap_min, expected):
    recs = [rec(0, cookie_sid_hash="c", ip_hash="h1"), rec(gap_min * 60, path="/cart", cookie_sid_hash="c", ip_hash="h1")]
    assert len(sessions(run(tmp_path, recs))) == expected


@pytest.mark.parametrize(("gap_min", "expected"), [(9, 1), (11, 2)])
def test_agent_timeout_is_10_minutes(tmp_path, gap_min, expected):
    recs = [
        rec(0, user_agent=GPT_UA, ip_hash="a1", accept="*/*"),
        rec(gap_min * 60, path="/p/x", user_agent=GPT_UA, ip_hash="a1", accept="*/*"),
    ]
    con = run(tmp_path, recs)
    rows = sessions(con)
    assert len(rows) == expected and all(r[4] == "declared" for r in rows)


def test_cookie_beats_ip_ua_and_follows_ip_changes(tmp_path):
    recs = [
        rec(0, cookie_sid_hash="c1", ip_hash="ip-1"),
        rec(60, path="/cart", cookie_sid_hash="c1", ip_hash="ip-2"),  # same cookie, mobile network switch
        rec(30, cookie_sid_hash="c2", ip_hash="ip-1"),  # same ip+ua, different cookie
    ]
    rows = sessions(run(tmp_path, recs))
    assert sorted(r[1] for r in rows) == [1, 2]


def test_cookieless_request_attaches_to_nearby_cookie_only(tmp_path):
    recs = [
        rec(0, cookie_sid_hash=None, ip_hash="ip-1"),  # first hit, before Set-Cookie
        rec(1, path="/c/x", cookie_sid_hash="c1", ip_hash="ip-1"),
        rec(3000, path="/cart", cookie_sid_hash=None, ip_hash="ip-1"),  # long after: falls back to ip+ua key
    ]
    rows = sessions(run(tmp_path, recs))
    assert sorted(r[1] for r in rows) == [1, 2]


def test_cookieless_agents_group_by_operator_ip_ua(tmp_path):
    recs = [rec(i * 20, path=f"/p/s{i}", user_agent=GPT_UA, ip_hash="a1", cookie_sid_hash=None, accept="*/*") for i in range(4)]
    recs += [rec(5, path="/", user_agent=GPT_UA, ip_hash="a2", accept="*/*")]  # other IP => other session
    rows = sessions(run(tmp_path, recs))
    assert sorted(r[1] for r in rows) == [1, 4]
    assert {r[4] for r in rows} == {"declared"}


def test_agent_cookie_churn_does_not_split_session(tmp_path):
    recs = [rec(i * 15, path=f"/p/s{i}", user_agent=GPT_UA, ip_hash="a1", cookie_sid_hash=f"new-{i}", accept="*/*") for i in range(3)]
    assert [r[1] for r in sessions(run(tmp_path, recs))] == [3]


def test_counts_entry_exit_and_beacon(tmp_path):
    recs = [
        rec(0, path="/p/x", cookie_sid_hash="c"),
        rec(0.2, path="/_next/static/a.js", is_asset=True, cookie_sid_hash="c"),
        rec(1, path="/api/beacon", method="POST", status=204, event_type="beacon", cookie_sid_hash="c"),
        rec(10, path="/cart", cookie_sid_hash="c"),
        rec(10.5, path="/img/a.png", is_asset=True, cookie_sid_hash="c"),
    ]
    (row,) = sessions(run(tmp_path, recs))
    _, requests, pages, beacon, tier, entry, exit_, converted, value = row
    assert (requests, pages, beacon, tier) == (5, 2, True, "human")
    assert (entry, exit_) == ("/p/x", "/cart")
    assert converted is False and value is None


def test_session_inherits_strongest_identity(tmp_path):
    # unsigned asset/beacon requests with the declared UA share the session of the declared page requests
    recs = [
        rec(0, user_agent=GPT_UA, ip_hash="a1", accept="*/*"),
        rec(1, path="/api/beacon", user_agent=GPT_UA, ip_hash="a1", event_type="beacon", method="POST"),
    ]
    con = run(tmp_path, recs)
    (row,) = sessions(con)
    assert row[4] == "declared"
    assert con.execute("SELECT count(*) FROM requests WHERE session_id IS NULL").fetchall() == [(0,)]


def test_order_linked_by_checkout_request_and_by_cookie(tmp_path):
    checkout = rec(100, path="/api/checkout", method="POST", status=201, cookie_sid_hash=None, user_agent=GPT_UA,
                   ip_hash="a1", meta={"order_id": "DT-A", "cart_value": 2500, "payment_method": "UPI"})  # fmt: skip
    recs = [
        rec(0, path="/p/x", user_agent=GPT_UA, ip_hash="a1", accept="*/*"),
        checkout,
        rec(0, cookie_sid_hash="ck", ip_hash="h1"),
        rec(200, path="/checkout", cookie_sid_hash="ck", ip_hash="h1"),
        rec(0, cookie_sid_hash="other", ip_hash="h2"),
    ]
    orders = [
        {"order_id": "DT-B", "session_cookie_id": "ck", "cart_value": 999, "ts": rec(260)["ts"], "payment_method": "COD"},
        {"order_id": "DT-C", "session_cookie_id": "never-seen", "cart_value": 1, "ts": rec(300)["ts"],
         "payment_method": "COD"},
    ]  # fmt: skip
    con = run(tmp_path, recs, orders)
    linked = dict(con.execute("SELECT order_id, session_id IS NOT NULL FROM orders").fetchall())
    assert linked == {"DT-A": True, "DT-B": True, "DT-C": False}
    conv = con.execute(
        "SELECT identity_tier, order_id, order_value FROM sessions WHERE converted ORDER BY order_value"
    ).fetchall()
    assert conv == [("human", "DT-B", 999.0), ("declared", "DT-A", 2500.0)]
    assert con.execute("SELECT count(*) FROM sessions WHERE converted").fetchall() == [(2,)]
    assert con.execute("SELECT max_stage, terminal_blocker_id FROM sessions LIMIT 1").fetchall() == [(None, None)]


def test_sessionize_is_idempotent_and_stable(tmp_path):
    recs = [rec(i * 40, path=f"/p/s{i}", cookie_sid_hash="c") for i in range(5)]
    con = run(tmp_path, recs)
    first = con.execute("SELECT session_id, request_count FROM sessions ORDER BY 1").fetchall()
    sessionize(con)
    assert con.execute("SELECT session_id, request_count FROM sessions ORDER BY 1").fetchall() == first
