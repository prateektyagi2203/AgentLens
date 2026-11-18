"""C7 blocker rules: positive and negative cases per blocker, built from hand-written agent sessions."""

from __future__ import annotations

import json
from datetime import datetime

import agentlens.funnel  # noqa: F401  (registers the step)
import pytest
from agentlens import db, pipeline
from agentlens.diagnosis import engine
from helpers import rec, write_jsonl

FETCHER_UA = "Mozilla/5.0 (compatible; ChatGPT-User/1.0)"
CRAWLER_UA = "Mozilla/5.0 (compatible; GPTBot/1.1; +https://openai.com/gptbot)"
CATALOG = engine.load_catalog(None)
PRODUCT = next(p for p in CATALOG if any(v["stock"] <= 0 for v in p["variants"]) and any(v["stock"] > 0 for v in p["variants"]))
EMPTY_VARIANT = next(v for v in PRODUCT["variants"] if v["stock"] <= 0)


def step(path, status=200, *, method="GET", code=None, ms=50, **meta):
    return {"path": path, "status": status, "method": method, "code": code, "ms": ms, "meta": meta}


def build(tmp_path, steps, *, ua=FETCHER_UA, patch=None, checks=None, session="a"):
    """Ingest one agent session made of `steps`, run the pipeline up to funnel, optionally patch the session row."""
    logs = tmp_path / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    records = []
    for i, s in enumerate(steps):
        meta = dict(s["meta"])
        if s["code"]:
            meta["error_code"] = s["code"]
        records.append(rec(i * 4, path=s["path"], method=s["method"], status=s["status"], duration_ms=s["ms"], user_agent=ua,
                           ip_hash=f"ip-{session}", accept="*/*", sec_fetch_mode=None, sec_fetch_dest=None, sec_fetch_site=None,
                           meta=meta))  # fmt: skip
    write_jsonl(logs / f"access-{session}.jsonl", records)
    con = db.connect(":memory:")
    res = pipeline.run_steps(con, ["ingest", "identify", "sessionize", "funnel"], {"source": str(logs), "fmt": "jsonl"})
    assert res.ok, res.steps
    for name, result, details in checks or []:
        con.execute("INSERT INTO site_checks VALUES (?, ?, ?, '', ?, ?)",
                    [f"c-{name}-{result}", datetime(2026, 1, 1), name, result, json.dumps(details or {})])  # fmt: skip
    if patch:
        con.execute(f"UPDATE sessions SET {patch}")
    return con


def diagnose(con):
    engine.diagnose(con, pipeline.RunContext("t", {"skip_site_probe": True, "llm_provider": "off"}))
    return con.execute("SELECT terminal_blocker_id, blocker_confidence FROM sessions WHERE identity_tier <> 'human'").fetchone()


def blocker(tmp_path, steps, **kw):
    row = diagnose(build(tmp_path, steps, **kw))
    return row[0] if row else None


PDP = step("/p/white-sneaker")
CART_OK = step("/api/cart", 201, method="POST", unit_price=PRODUCT["price"], product_id=PRODUCT["id"])
CART_409 = step("/api/cart", 409, method="POST", code="PINCODE_REQUIRED")


@pytest.mark.parametrize(
    ("steps", "expected"),
    [
        ([PDP, step("/api/cart", 409, method="POST", code="PINCODE_REQUIRED")], "B05"),
        ([PDP, CART_409, step("/api/serviceability", 200), step("/api/cart", 201, method="POST")], None),  # recovered
        ([PDP, step("/api/cart", 401, method="POST", code="AUTH_REQUIRED")], "B06"),
        ([PDP, step("/api/cart", 401, method="POST", code="AUTH_REQUIRED"), step("/login"), step("/api/otp/send", 200, method="POST"),
          step("/api/cart", 201, method="POST")], None),  # logged in, carted
        ([PDP, CART_OK, step("/checkout"), step("/api/checkout", 403, method="POST", code="CAPTCHA_REQUIRED")], "B02"),
        ([PDP, CART_OK, step("/checkout"), step("/api/checkout", 403, method="POST", code="CAPTCHA_REQUIRED"),
          step("/api/checkout", 201, method="POST")], None),  # solved
        ([PDP, CART_OK, step("/checkout"), step("/api/checkout", 422, method="POST", code="PHONE_FORMAT")], "B10"),
        ([PDP, CART_OK, step("/checkout"), step("/api/checkout", 409, method="POST", code="COD_OTP_REQUIRED")], "B11"),
        ([PDP, step("/api/products/X/variants", 409, code="OUT_OF_STOCK")], "B08"),
        ([PDP, step("/api/products/X/variants", 409, code="OUT_OF_STOCK"), step("/api/products/X/variants", 200)], None),  # other variant
        ([step("/"), step("/api/x", 403, code="BOT_CHALLENGE")], "B01"),
        ([step("/"), step("/p/a", 429, code="RATE_LIMITED")], "B12"),
        ([step("/"), step("/p/a", 200, ms=7500)], "B13"),
        ([step("/"), step("/p/a", 200, ms=900)], None),  # fast and ordinary
        ([step("/"), step("/p/gone-old", 404)], "B16"),
        ([step("/robots.txt"), step("/p/x", 200)], None),  # read a PDP after robots: not B14
    ],
)
def test_code_driven_rules(tmp_path, steps, expected):
    assert blocker(tmp_path, steps) == expected


def test_b08_catalog_flags_out_of_stock_variant_returned_as_200(tmp_path):
    query = f"size={EMPTY_VARIANT['size'].replace(' ', '+')}&colour={EMPTY_VARIANT['colour'].replace(' ', '+')}"
    var = step(f"/api/products/{PRODUCT['id']}/variants", 200)
    var["query"] = query
    # the helper has no query column: write it by rebuilding the record
    con = build(tmp_path, [PDP, var])
    con.execute("UPDATE requests SET query = ? WHERE page_type = 'variant_api'", [query])
    assert diagnose(con)[0] == "B08"


def test_b15_price_mismatch_between_catalog_and_cart(tmp_path):
    bad = step("/api/cart", 201, method="POST", unit_price=PRODUCT["price"] + 500, product_id=PRODUCT["id"])
    assert blocker(tmp_path, [PDP, bad, step("/cart")]) is None  # agent viewed the cart afterwards: not the last request
    assert blocker(tmp_path / "x", [PDP, bad]) == "B15"
    assert blocker(tmp_path / "y", [PDP, CART_OK]) is None


@pytest.mark.parametrize(
    ("checks", "expected"),
    [
        ([("pdp_ssr_price", "fail", None)], "B03"),
        ([("pdp_ssr_price", "pass", None)], None),
        ([("pdp_ssr_price", "pass", None), ("pdp_jsonld_product", "fail", None)], "B04"),
        ([("pdp_ssr_price", "fail", None), ("pdp_jsonld_product", "fail", None)], "B03"),  # B03 wins the tie
        ([], None),  # no site evidence: never confident enough
    ],
)
def test_content_rules_need_site_checks(tmp_path, checks, expected):
    assert blocker(tmp_path, [step("/"), PDP], checks=checks) == expected


def test_b09_size_guide_image_only(tmp_path):
    steps = [step("/"), step("/size-guide/mens-sneakers")]
    assert blocker(tmp_path, steps, checks=[("size_guide_table", "fail", None)]) == "B09"
    assert blocker(tmp_path / "p", steps, checks=[("size_guide_table", "pass", None)]) is None
    assert blocker(tmp_path / "u", steps) is None  # unknown: confidence 0.45 < terminal minimum


def test_b14_robots_disallow_uses_site_check_when_available(tmp_path):
    steps = [step("/robots.txt")]
    blocked = [("robots_txt", "fail", {"blocked_agents": ["chatgpt-user"]})]
    assert blocker(tmp_path, steps, checks=blocked) == "B14"
    other = [("robots_txt", "fail", {"blocked_agents": ["gptbot"]})]
    assert blocker(tmp_path / "o", steps, checks=other) is None
    assert blocker(tmp_path / "n", steps) == "B14"  # no site check: stopping right after robots.txt still reads as B14 (0.7)


def test_b07_browsing_agent_stops_on_loaded_pdp(tmp_path):
    steps = [step("/"), PDP]
    patch = "identity_tier = 'suspected', agent_class = 'browsing_agent', has_beacon = true"
    assert blocker(tmp_path, steps, patch=patch) == "B07"
    assert blocker(tmp_path / "f", steps) is None  # a fetcher ending on a PDP is not a popup victim


def test_crawlers_only_get_infrastructure_rules(tmp_path):
    steps = [step("/robots.txt"), step("/p/a", 429, code="RATE_LIMITED")]
    assert blocker(tmp_path, steps, ua=CRAWLER_UA) == "B12"
    assert blocker(tmp_path / "x", [step("/p/a"), step("/api/cart", 409, method="POST", code="PINCODE_REQUIRED")], ua=CRAWLER_UA) is None


def test_hits_have_request_evidence_and_one_terminal(tmp_path):
    con = build(tmp_path, [PDP, step("/api/cart", 409, method="POST", code="PINCODE_REQUIRED")])
    diagnose(con)
    rows = con.execute("SELECT blocker_id, is_terminal, evidence_json FROM blocker_hits").fetchall()
    assert [(b, t) for b, t, _ in rows] == [("B05", True)]
    ev = json.loads(rows[0][2])
    assert ev[0]["type"] == "request" and "409 PINCODE_REQUIRED" in ev[0]["summary"]
    rid = con.execute("SELECT request_id FROM requests WHERE status = 409").fetchone()[0]
    assert ev[0]["request_id"] == rid


def test_converted_sessions_are_not_diagnosed(tmp_path):
    steps = [PDP, CART_OK, step("/checkout"), step("/api/checkout", 201, method="POST", order_id="o1", cart_value=2000)]
    assert blocker(tmp_path, steps, patch="converted = true") is None


def test_unexplained_failures_are_b99(tmp_path):
    steps = [step("/"), PDP, step("/api/cart", 500, method="POST")]
    con = build(tmp_path, steps)
    engine.diagnose(con, pipeline.RunContext("t", {"skip_site_probe": True, "llm_provider": "off"}))
    assert con.execute("SELECT terminal_blocker_id, diagnosis_method FROM sessions WHERE identity_tier <> 'human'").fetchone() == ("B99", "rules")
