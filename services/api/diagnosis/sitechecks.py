"""Site checks (PRD 12.4/12.5): probe the live store for the conditions that cannot be seen in access logs.

    robots_txt          AI agent tokens disallowed from /p/ (details.blocked_agents)          fail | pass | missing
    llms_txt            /llms.txt present                                                      pass | missing
    sitemap             Sitemap: line in robots.txt or /sitemap.xml present                    pass | missing
    pdp_ssr_price       price visible in server-rendered HTML (no JavaScript)                  pass | warn | fail
    pdp_jsonld_product  schema.org Product JSON-LD with an offer price                         pass | warn | fail
    size_guide_table    size guide has an HTML table, not only an image                        pass | fail
    captcha_presence    /api/captcha challenge endpoint exists                                 fail (present) | pass

Probing happens only when a base URL is configured (`site_checks.base_url`, env AGENTLENS_SITE_URL or `--site-url`).
Without one, or when the store is unreachable, one `site_probe` row with result `skipped` is recorded and diagnosis
falls back to log evidence only (lower confidence for content rules). Results are history rows; diagnosis picks the
check valid at each session's start.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import duckdb
import httpx

CHECK_NAMES = (
    "robots_txt", "llms_txt", "sitemap", "pdp_ssr_price", "pdp_jsonld_product", "size_guide_table", "captcha_presence",
)  # fmt: skip
USABLE = ("pass", "fail", "warn", "missing")  # results diagnosis may rely on (skipped/error are not evidence)
_SCRIPT = re.compile(r"<script\b.*?</script>|<style\b.*?</style>", re.S | re.I)
_PRICE = re.compile(r"₹\s*\d|&#8377;\s*\d|INR\s*\d")
_LD = re.compile(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", re.S | re.I)


@dataclass
class CheckResult:
    check_name: str
    target: str
    result: str
    details: dict[str, Any] = field(default_factory=dict)


def parse_robots(text: str, path: str = "/p/") -> list[str]:
    """Lower-cased user-agent tokens whose group disallows `path` (a rule that is a prefix of it, or `/`)."""
    blocked: list[str] = []
    agents: list[str] = []
    in_rules = False
    disallows: list[str] = []

    def flush() -> None:
        if any(d and path.startswith(d) for d in disallows):
            blocked.extend(a for a in agents if a != "*")

    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if in_rules:
                flush()
                agents, disallows, in_rules = [], [], False
            agents.append(value.lower())
        elif key == "disallow":
            in_rules = True
            disallows.append(value)
        elif key in ("allow", "crawl-delay"):
            in_rules = True
    flush()
    return sorted(set(blocked))


def _get(client: httpx.Client, base: str, path: str) -> httpx.Response | None:
    try:
        return client.get(base.rstrip("/") + path)
    except httpx.HTTPError:
        return None


def _check_robots(client: httpx.Client, base: str) -> list[CheckResult]:
    resp = _get(client, base, "/robots.txt")
    if resp is None:
        raise httpx.ConnectError("robots.txt unreachable")
    if resp.status_code != 200:
        return [CheckResult("robots_txt", "/robots.txt", "missing", {"status": resp.status_code}),
                CheckResult("sitemap", "/robots.txt", "missing", {"status": resp.status_code})]  # fmt: skip
    blocked = parse_robots(resp.text)
    out = [CheckResult("robots_txt", "/robots.txt", "fail" if blocked else "pass", {"blocked_agents": blocked})]
    has_sitemap = bool(re.search(r"^\s*sitemap:", resp.text, re.I | re.M))
    if not has_sitemap:
        sm = _get(client, base, "/sitemap.xml")
        has_sitemap = sm is not None and sm.status_code == 200
    out.append(CheckResult("sitemap", "/robots.txt", "pass" if has_sitemap else "missing", {}))
    return out


def _pdp_paths(con: duckdb.DuckDBPyConnection, n: int, catalog_slugs: list[str], seed: int) -> list[str]:
    rows = con.execute(
        "SELECT path FROM requests WHERE page_type = 'pdp' AND status = 200 GROUP BY path ORDER BY count(*) DESC, path LIMIT 200"
    ).fetchall()
    paths = [r[0] for r in rows] or [f"/p/{s}" for s in catalog_slugs]
    rng = random.Random(seed)
    return sorted(rng.sample(paths, min(n, len(paths))))


def _ld_products(html: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for block in _LD.findall(html):
        try:
            doc = json.loads(block)
        except ValueError:
            continue
        items = doc if isinstance(doc, list) else [doc]
        for it in items:
            if isinstance(it, dict) and it.get("@type") == "Product":
                found.append(it)
    return found


def _offer_price(product: dict[str, Any]) -> bool:
    offers = product.get("offers")
    offers_l = offers if isinstance(offers, list) else [offers]
    return any(isinstance(o, dict) and o.get("price") not in (None, "") for o in offers_l)


def _check_pdps(client: httpx.Client, base: str, paths: list[str]) -> list[CheckResult]:
    if not paths:
        return []
    ssr_ok = ld_complete = ld_basic = fetched = 0
    for p in paths:
        resp = _get(client, base, p)
        if resp is None or resp.status_code != 200:
            continue
        fetched += 1
        html = resp.text
        ssr_ok += bool(_PRICE.search(_SCRIPT.sub("", html)))
        prods = _ld_products(html)
        if prods:
            if any(_offer_price(x) for x in prods):
                ld_complete += 1
            else:
                ld_basic += 1
    if not fetched:
        return []

    def verdict(ok: int, partial: int = 0) -> str:
        if ok == fetched:
            return "pass"
        return "fail" if ok + partial == 0 else "warn"

    return [
        CheckResult("pdp_ssr_price", "/p/*", verdict(ssr_ok), {"sampled": fetched, "with_price": ssr_ok}),
        CheckResult("pdp_jsonld_product", "/p/*", verdict(ld_complete, ld_basic),
                    {"sampled": fetched, "complete": ld_complete, "without_offer": ld_basic}),
    ]  # fmt: skip


def _check_size_guide(client: httpx.Client, base: str) -> list[CheckResult]:
    resp = _get(client, base, "/size-guide/mens-sneakers")
    if resp is None or resp.status_code != 200:
        return []
    html = _SCRIPT.sub("", resp.text)
    has_table = "<table" in html.lower() or 'data-testid="size-table"' in html
    return [CheckResult("size_guide_table", "/size-guide/*", "pass" if has_table else "fail", {})]


def _check_aux(client: httpx.Client, base: str) -> list[CheckResult]:
    llms = _get(client, base, "/llms.txt")
    cap = _get(client, base, "/api/captcha")
    out = [CheckResult("llms_txt", "/llms.txt", "pass" if llms is not None and llms.status_code == 200 else "missing", {})]
    if cap is not None:
        out.append(CheckResult("captcha_presence", "/api/captcha", "fail" if cap.status_code == 200 else "pass",
                               {"status": cap.status_code}))  # fmt: skip
    return out


def run_site_checks(
    con: duckdb.DuckDBPyConnection,
    base_url: str | None,
    *,
    transport: httpx.BaseTransport | None = None,
    now: datetime | None = None,
    timeout_s: float = 5.0,
    pdp_sample: int = 5,
    catalog_slugs: list[str] | None = None,
    seed: int = 0,
) -> dict[str, Any]:
    """Probe the store and append rows to `site_checks`. Never raises on network problems: records `skipped`."""
    run_ts = (now or datetime.now(UTC)).replace(tzinfo=None, microsecond=0)
    if not base_url:
        return _record_skip(con, run_ts, "", "no base URL configured")
    try:
        with httpx.Client(transport=transport, timeout=timeout_s, follow_redirects=True) as client:
            results = _check_robots(client, base_url)
            results += _check_pdps(client, base_url, _pdp_paths(con, pdp_sample, catalog_slugs or [], seed))
            results += _check_size_guide(client, base_url)
            results += _check_aux(client, base_url)
    except httpx.HTTPError as exc:
        return _record_skip(con, run_ts, base_url, f"store unreachable: {type(exc).__name__}")
    rows = [
        (hashlib.sha1(f"{run_ts.isoformat()}|{base_url}|{r.check_name}".encode()).hexdigest()[:16], run_ts, r.check_name,
         r.target, r.result, json.dumps(r.details, sort_keys=True))
        for r in results
    ]  # fmt: skip
    con.executemany("INSERT OR REPLACE INTO site_checks VALUES (?, ?, ?, ?, ?, ?)", rows)
    return {"status": "ok", "checks": len(rows), "results": {r.check_name: r.result for r in results}}


def _record_skip(con: duckdb.DuckDBPyConnection, run_ts: datetime, target: str, reason: str) -> dict[str, Any]:
    day = run_ts.date().isoformat()
    con.execute(
        "INSERT OR REPLACE INTO site_checks VALUES (?, ?, 'site_probe', ?, 'skipped', ?)",
        [f"skipped-{day}", run_ts, target, json.dumps({"reason": reason})],
    )
    return {"status": "skipped", "reason": reason, "checks": 0}


def site_check_summary(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    """Latest usable result per check (for the dashboard's checklist)."""
    rows = con.execute(
        """
        SELECT check_name, arg_max(result, run_ts), max(run_ts), arg_max(details_json, run_ts)
        FROM site_checks WHERE result IN ('pass', 'fail', 'warn', 'missing') GROUP BY check_name ORDER BY check_name
        """
    ).fetchall()
    return [{"check": r[0], "result": r[1], "run_ts": r[2], "details": json.loads(r[3] or "{}")} for r in rows]
