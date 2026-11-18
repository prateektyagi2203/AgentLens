"""C3 ingestion: formats, incremental offsets, quarantine, idempotency, side tables."""

from __future__ import annotations

import hashlib
import json

import pytest
from agentlens import db
from agentlens.ingest import ingest_path
from helpers import BROWSER_UA, rec, write_jsonl


@pytest.fixture()
def con():
    c = db.connect(":memory:")
    yield c
    c.close()


def count(con, table="requests"):
    return con.execute(f"SELECT count(*) FROM {table}").fetchall()[0][0]


def test_basic_load_classification_and_derived_fields(con, tmp_path):
    records = [
        rec(0, path="/"),
        rec(1, path="/c/sneakers"),
        rec(2, path="/p/mustard-sneaker"),
        rec(3, path="/_next/static/a.js", is_asset=True),
        rec(4, path="/api/beacon", method="post", status=204, event_type="beacon"),
        rec(5, path="/api/cart", method="POST", status=409, meta={"error_code": "PINCODE_REQUIRED"}),
        rec(6, path="/something/unknown"),
        rec(7, path="/api/checkout", method="POST", status=422, meta={"error_code": "PHONE_FORMAT"}),
    ]
    log = write_jsonl(tmp_path / "access-2026-11-01.jsonl", records)
    res = ingest_path(con, log)
    assert (res.lines, res.requests_inserted, res.errors) == (8, 8, 0)
    types = dict(con.execute("SELECT path, page_type FROM requests").fetchall())
    assert types["/"] == "home" and types["/c/sneakers"] == "plp" and types["/p/mustard-sneaker"] == "pdp"
    assert types["/_next/static/a.js"] == "asset" and types["/api/beacon"] == "beacon"
    assert types["/api/cart"] == "cart_api" and types["/something/unknown"] == "other"
    codes = dict(con.execute("SELECT path, error_code FROM requests WHERE error_code IS NOT NULL").fetchall())
    assert codes == {"/api/cart": "PINCODE_REQUIRED", "/api/checkout": "PHONE_FORMAT"}
    assert con.execute("SELECT DISTINCT method FROM requests WHERE path = '/api/beacon'").fetchall() == [("POST",)]
    ua_hash = con.execute("SELECT DISTINCT ua_hash FROM requests").fetchall()
    assert ua_hash == [(hashlib.sha256(BROWSER_UA.encode()).hexdigest(),)]


def test_idempotent_by_request_id_and_offsets(con, tmp_path):
    log = write_jsonl(tmp_path / "a.jsonl", [rec(i) for i in range(5)])
    first = ingest_path(con, log)
    second = ingest_path(con, log)
    assert first.requests_inserted == 5 and second.lines == 0 and count(con) == 5
    # a copy of the same records in another file is deduplicated by request_id
    text = log.read_text(encoding="utf-8")
    (tmp_path / "b.jsonl").write_text(text, encoding="utf-8")
    third = ingest_path(con, tmp_path / "b.jsonl")
    assert third.requests_inserted == 0 and third.duplicates == 5 and count(con) == 5


def test_incremental_append(con, tmp_path):
    log = tmp_path / "a.jsonl"
    write_jsonl(log, [rec(0), rec(1), rec(2)])
    ingest_path(con, log)
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec(3)) + "\n" + json.dumps(rec(4)) + "\n")
    res = ingest_path(con, log)
    assert (res.lines, res.requests_inserted) == (2, 2) and count(con) == 5
    offset = con.execute("SELECT last_offset FROM ingest_state").fetchall()[0][0]
    assert offset == log.stat().st_size


def test_partial_last_line_is_left_for_next_run(con, tmp_path):
    log = tmp_path / "a.jsonl"
    complete = json.dumps(rec(0)) + "\n"
    half = json.dumps(rec(1))
    log.write_text(complete + half[:40], encoding="utf-8")
    res = ingest_path(con, log)
    assert res.requests_inserted == 1 and res.errors == 0 and count(con, "ingest_errors") == 0
    log.write_text(complete + half + "\n", encoding="utf-8")  # the writer finished the line
    res = ingest_path(con, log)
    assert res.requests_inserted == 1 and count(con) == 2 and count(con, "ingest_errors") == 0


def test_bad_lines_are_quarantined_not_fatal(con, tmp_path):
    good = json.dumps(rec(0))
    log = tmp_path / "a.jsonl"
    log.write_text(
        "\n".join([good, "{not json", '{"ts": "yesterday"}', json.dumps({**rec(1), "request_id": None}), "[1, 2]",
                   json.dumps(rec(2))]) + "\n",  # fmt: skip
        encoding="utf-8",
    )
    res = ingest_path(con, log)
    assert res.requests_inserted == 2 and res.errors == 4
    errs = con.execute("SELECT line_no, error FROM ingest_errors ORDER BY line_no").fetchall()
    assert [e[0] for e in errs] == [2, 3, 4, 5]
    assert all(e[1] for e in errs)


def test_config_change_and_orders_go_to_their_own_tables(con, tmp_path):
    records = [
        rec(0, path="/api/checkout", method="POST", status=201, cookie_sid_hash="ck1",
            meta={"order_id": "DT-1", "cart_value": 1999, "payment_method": "UPI"}),  # fmt: skip
        rec(1, event_type="order", path="/api/checkout", method="POST", cookie_sid_hash="ck1",
            meta={"order_id": "DT-1", "cart_value": 1999, "payment_method": "UPI"}),  # fmt: skip
        rec(2, event_type="config_change", path="-", meta={"toggles": {"F05": False}, "changed": ["F05"]}),
    ]
    (tmp_path / "orders.jsonl").write_text(
        json.dumps({"order_id": "DT-2", "session_cookie_id": "ck2", "cart_value": 500, "ts": records[0]["ts"],
                    "payment_method": "COD"}) + "\n",  # fmt: skip
        encoding="utf-8",
    )
    logs = tmp_path / "logs"
    logs.mkdir()
    write_jsonl(logs / "access-2026-11-01.jsonl", records)
    ingest_path(con, logs)
    assert count(con) == 1  # only the checkout request; order and config_change lines are not requests
    orders = con.execute("SELECT order_id, order_value, cookie_sid_hash, request_id FROM orders ORDER BY 1").fetchall()
    assert orders[0][:3] == ("DT-1", 1999.0, "ck1") and orders[0][3] == records[0]["request_id"]
    assert orders[1][:3] == ("DT-2", 500.0, "ck2")
    ann = con.execute("SELECT type, label FROM annotations").fetchall()
    assert ann == [("config_change", "F05 off")]
    ingest_path(con, logs)
    assert count(con, "orders") == 2 and count(con, "annotations") == 1


def test_signature_headers_go_to_side_table(con, tmp_path):
    records = [
        rec(0, request_id="signed", signature="sig1=:AAAA:", signature_input="sig1=();created=1",
            signature_agent='sig1="https://agents.desithreads.test"'),  # fmt: skip
        rec(1, request_id="plain"),
    ]
    ingest_path(con, write_jsonl(tmp_path / "a.jsonl", records))
    flags = dict(con.execute("SELECT request_id, has_signature FROM requests").fetchall())
    assert flags == {"signed": True, "plain": False}
    side = con.execute("SELECT request_id, signature, authority, path FROM request_signatures").fetchall()
    assert side == [("signed", "sig1=:AAAA:", "desithreads.local", "/")]
    origin = con.execute("SELECT signature_agent FROM requests WHERE request_id = 'signed'").fetchall()
    assert origin == [("https://agents.desithreads.test",)]


def test_synth_link_field_is_never_stored(con, tmp_path):
    records = [rec(i, meta={"synth_session_id": f"syn-{i}", "product_id": "SNK001"}) for i in range(3)]
    records.append(rec(9, event_type="order", meta={"order_id": "DT-9", "cart_value": 1, "synth_session_id": "syn-9"}))
    ingest_path(con, write_jsonl(tmp_path / "a.jsonl", records))
    for table in ("requests", "orders", "annotations", "ingest_errors", "request_signatures"):
        dumped = con.execute(f"SELECT to_json(t) FROM {table} t").fetchall()
        assert not any("syn-" in str(r[0]) or "synth_session" in str(r[0]) for r in dumped), table
    cols = {
        r[0]
        for r in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name IN ('requests', 'orders', 'annotations')"
        ).fetchall()
    }
    assert not any("synth" in c for c in cols)


NGINX_LINES = [
    '203.0.113.7 - - [01/Nov/2026:10:00:00 +0000] "GET /p/mustard-sneaker?x=1 HTTP/1.1" 200 5123 "-" "Mozilla/5.0 (X11) Chrome/131"',
    '203.0.113.7 - - [01/Nov/2026:15:30:05 +0530] "POST /api/cart HTTP/1.1" 409 55 "https://shop/p/x" "UA \\"quoted\\"" "-" "-" "-" 0.250',
    '198.51.100.9 - - [01/Nov/2026:10:00:09 +0000] "GET /p/x HTTP/1.1" 200 10 "-" "TestSignedAgent/1.0" "sig1=:AAAA:" '
    '"sig1=(\\"@authority\\");created=1" "sig1=\\"https://agents.desithreads.test\\"" 0.010',
    "garbage line that is not nginx",
]


def test_nginx_combined_with_signature_fields(con, tmp_path):
    log = tmp_path / "access.log"
    log.write_text("\n".join(NGINX_LINES) + "\n", encoding="utf-8")
    res = ingest_path(con, log, "nginx_combined", default_host="desithreads.local")
    assert (res.requests_inserted, res.errors) == (3, 1)
    rows = con.execute(
        "SELECT method, path, query, status, ts, host, page_type, duration_ms, has_signature, user_agent "
        "FROM requests ORDER BY ts"
    ).fetchall()  # fmt: skip
    assert rows[0][:4] == ("GET", "/p/mustard-sneaker", "x=1", 200)
    assert rows[0][4].isoformat() == "2026-11-01T10:00:00" and rows[0][5] == "desithreads.local"
    assert rows[0][6] == "pdp" and rows[0][8] is False
    # +0530 local time is converted to UTC; the trailing request-time field becomes duration_ms
    quoted = [r for r in rows if r[1] == "/api/cart"][0]
    assert quoted[4].isoformat() == "2026-11-01T10:00:05"
    assert quoted[7] == 250 and quoted[9] == 'UA "quoted"'
    signed = [r for r in rows if r[8]]
    assert len(signed) == 1
    assert count(con, "request_signatures") == 1
    # same file again: stable ids from file offsets => no duplicates
    again = ingest_path(con, log, "nginx_combined", default_host="desithreads.local")
    assert again.lines == 0 and count(con) == 3
    # a rewritten (truncated) file is re-read from the start and deduplicated
    log.write_text("\n".join(NGINX_LINES[:1]) + "\n", encoding="utf-8")
    assert ingest_path(con, log, "nginx_combined").requests_inserted == 0


def test_unknown_format_rejected(con, tmp_path):
    with pytest.raises(ValueError):
        ingest_path(con, write_jsonl(tmp_path / "a.jsonl", [rec(0)]), "csv")
