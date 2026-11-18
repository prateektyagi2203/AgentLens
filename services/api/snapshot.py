"""Static demo snapshot (`agentlens export-snapshot`): the dashboard's API responses written as `/demo/*.json`.

The layout is the one in docs/api-contract.md section 4. Every file is the response of the real FastAPI route, called
in-process, so the snapshot cannot drift from the API. It contains no ground truth, no raw IPs and no PII (the export
fails if a scan finds any), and `meta.json` carries `demo_mode` and `synthetic` so the dashboard labels it as synthetic.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi.testclient import TestClient

from . import settings
from .routers import analytics as an
from .routers.deps import DB, Filters, slug

SEGMENTS = ("all_agents", "verified", "declared", "suspected", "humans")
BLOCKER_IDS = [f"B{i:02d}" for i in range(1, 17)] + ["B99"]
STORE_NAME = "Demo Store (synthetic)"

# Sample sizes for sessions.json: the explorer filters client-side, so the snapshot keeps a bounded, mixed sample.
SAMPLE = {"blocked": 130, "converted": 50, "other_agents": 50, "humans": 70}

FORBIDDEN_KEYS = ("synth_session_id", "ground_truth", "groundtruth")
IPV4 = re.compile(r"(?<![\w./-])(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?![\w.-])")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
LOCAL_IPS = {"127.0.0.1", "0.0.0.0"}  # loopback literals are not personal data


class SnapshotError(RuntimeError):
    pass


class _Writer:
    def __init__(self, out: Path) -> None:
        self.out = out
        self.files: list[Path] = []

    def write(self, rel: str, data: Any) -> None:
        path = self.out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=1)
        path.write_text(text, encoding="utf-8")
        self.files.append(path)


def _prepare(out: Path, force: bool) -> None:
    if out.exists() and any(out.iterdir()):
        if not (out / "meta.json").exists() and not force:
            raise SnapshotError(f"{out} is not empty and does not look like a snapshot; pass --force to replace it")
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)


def _sample_ids(cur: Any, ctx: an.Ctx) -> list[str]:
    """Deterministic mixed sample: blocked agents (spread over blockers), converted agents, other agents, humans."""
    agent, _ = an.population(ctx, Filters(segment="all_agents"), None)
    human, _ = an.population(ctx, Filters(segment="humans"), None)
    picked: dict[str, None] = {}

    def take(sql: str, limit: int) -> None:
        for (sid,) in cur.execute(sql, [limit]).fetchall():
            picked.setdefault(sid, None)

    take(
        f"""SELECT session_id FROM (
              SELECT session_id, row_number() OVER (PARTITION BY terminal_blocker_id ORDER BY hash(session_id)) AS rn
              FROM sessions WHERE {agent} AND terminal_blocker_id IS NOT NULL AND NOT converted)
            ORDER BY rn, hash(session_id) LIMIT ?""",
        SAMPLE["blocked"],
    )
    take(f"SELECT session_id FROM sessions WHERE {agent} AND converted ORDER BY hash(session_id) LIMIT ?", SAMPLE["converted"])
    take(
        f"SELECT session_id FROM sessions WHERE {agent} AND terminal_blocker_id IS NULL AND NOT converted "
        "ORDER BY hash(session_id) LIMIT ?",
        SAMPLE["other_agents"],
    )
    take(f"SELECT session_id FROM sessions WHERE {human} ORDER BY hash(session_id) LIMIT ?", SAMPLE["humans"])
    return list(picked)


def _scan(files: list[Path]) -> None:
    """Fail the export if any file holds ground truth, a raw IP or an email address."""
    problems: list[str] = []
    for p in files:
        if p.suffix not in (".json", ".md", ".svg"):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        low = text.lower()
        problems += [f"{p.name}: key {k}" for k in FORBIDDEN_KEYS if k in low]
        problems += [f"{p.name}: IP {m}" for m in IPV4.findall(text) if m not in LOCAL_IPS]
        # A leading "+" is the user-agent contact convention of public bots ("+Claude-User@anthropic.com"), not a person.
        problems += [f"{p.name}: email {m}" for m in EMAIL.findall(text) if not m.startswith("+")]
    if problems:
        raise SnapshotError("snapshot privacy scan failed: " + "; ".join(problems[:10]))


def export_snapshot(out: Path, *, force: bool = False) -> dict[str, Any]:
    """Write the snapshot to `out` and return counts. The pipeline must have run; the API server must not hold the DB."""
    from .main import app

    if not settings.db_path().exists():
        raise SnapshotError(f"No database at {settings.db_path()}; run `agentlens run-all` first")
    _prepare(out, force)
    w = _Writer(out)
    DB.reset()
    client = TestClient(app)

    def get(path: str, **q: str) -> Any:
        r = client.get("/api" + path, params=q)
        if r.status_code != 200:
            raise SnapshotError(f"GET {path} {q} -> {r.status_code} {r.text[:200]}")
        return r.json() if "json" in r.headers.get("content-type", "") else r.text

    def get_optional(path: str, **q: str) -> Any | None:
        r = client.get("/api" + path, params=q)
        return r.json() if r.status_code == 200 else None

    ctx = an.load_ctx()
    meta = get("/meta")
    bounds = meta.get("date_bounds")
    if not bounds:
        raise SnapshotError("The database has no sessions; generate data and run the pipeline first")
    full = {"from": bounds["min"], "to": bounds["max"]}
    before = full
    cmp: dict[str, Any] | None = None
    after = None
    cmp_probe = get("/compare", a_from=full["from"], a_to=full["to"], b_from=full["from"], b_to=full["to"])
    if cmp_probe["suggested_windows"]:
        sw = cmp_probe["suggested_windows"][0]
        before, after = sw["a"], sw["b"]
        cmp = get("/compare", a_from=before["from"], a_to=before["to"], b_from=after["from"], b_to=after["to"])
    w.write("compare.json", cmp or cmp_probe)

    w.write("meta.json", {**meta, "demo_mode": True, "synthetic": True, "store_name": STORE_NAME})
    w.write("health.json", {**get("/health"), "demo_mode": True})
    w.write("overview.json", get("/overview", **{"from": full["from"], "to": full["to"]}))

    win = {"from": before["from"], "to": before["to"]}
    agents = get("/agents", **{"from": win["from"], "to": win["to"]})
    w.write("agents.json", agents)
    for a in agents["items"]:
        detail = get_optional(f"/agents/{quote(a['operator'], safe='')}/{quote(a['agent_name'], safe='')}", **{"from": win["from"], "to": win["to"]})
        if detail is not None:
            w.write(f"agents/{slug(a['operator'])}/{slug(a['agent_name'])}.json", detail)

    series: dict[str, Any] = {}
    stage_blockers: dict[str, Any] = {}
    base: dict[str, Any] | None = None
    for seg in SEGMENTS:
        f = get("/funnel", **{"from": win["from"], "to": win["to"], "segment": seg, "compare": "all_agents" if seg == "humans" else "humans"})
        series[seg] = f["primary"]
        stage_blockers[seg] = f["stage_blockers"]
        base = base or f
    assert base is not None
    w.write("funnel.json", {"window": base["window"], "stages": base["stages"], "series": series, "stage_blockers": stage_blockers})

    w.write("blockers.json", get("/blockers", **{"from": win["from"], "to": win["to"]}))
    for bid in BLOCKER_IDS:
        detail = get_optional(f"/blockers/{bid}", **{"from": win["from"], "to": win["to"]})
        if detail is not None:
            w.write(f"blockers/{bid}.json", detail)

    with DB.read() as cur:
        ids = _sample_ids(cur, ctx)
    rows: list[dict[str, Any]] = []
    for sid in ids:
        detail = get_optional(f"/sessions/{quote(sid, safe='')}")
        if detail is not None:
            rows.append(detail["session"])
            w.write(f"sessions/{sid}.json", detail)
    rows.sort(key=lambda r: (r["start_ts"], r["session_id"]), reverse=True)
    w.write("sessions.json", {"window": get("/overview", **{"from": full["from"], "to": full["to"]})["window"], "page": 1,
                              "page_size": len(rows), "total": len(rows), "items": rows})  # fmt: skip

    replays = get("/replays")
    w.write("replays.json", replays)
    shots = 0
    for item in replays["items"]:
        rid = item["replay_id"]
        detail = get_optional(f"/replays/{rid}")
        if detail is None:
            continue
        for step in detail["steps"]:
            url = step.get("screenshot_url")
            if not url:
                continue
            name = Path(url).name
            r = client.get(f"/api/replays/{quote(rid, safe='')}/screenshots/{quote(name, safe='')}")
            if r.status_code == 200:
                dest = out / "replays" / rid / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(r.content)
                w.files.append(dest)
                step["screenshot_url"] = f"/demo/replays/{rid}/{name}"
                shots += 1
            else:
                step["screenshot_url"] = None
        w.write(f"replays/{rid}.json", detail)

    w.write("annotations.json", get("/annotations"))
    w.write("recommendations.json", get("/recommendations", **{"from": win["from"], "to": win["to"]}))
    w.write("settings.json", get("/settings"))
    evaluation = get_optional("/eval/latest")
    if evaluation is not None:
        w.write("eval.json", evaluation)
    w.write("site-checks.json", get("/site-checks"))
    last = meta.get("last_run")
    if last:
        run = get_optional(f"/runs/{last['run_id']}")
        w.write(f"runs/{last['run_id']}.json", run or last)
    w.write("report.md", get("/report", format="md", **{"from": win["from"], "to": win["to"]}))

    _scan(w.files)
    DB.reset()
    return {
        "out": str(out), "files": len(w.files), "sessions": len(rows), "agents": len(agents["items"]), "replays": len(replays["items"]),
        "screenshots": shots, "eval": evaluation is not None, "before": win, "after": after, "bytes": sum(p.stat().st_size for p in w.files),
    }  # fmt: skip
