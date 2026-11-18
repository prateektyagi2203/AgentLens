"""Synthetic traffic written straight to native-schema JSONL, with no store running (PRD 17.1 offline mode).

Sessions are simulated against `SiteSim`, which mirrors the store's responses for all 16 toggles at the timestamp of each
request. Output: `<data>/logs/access-YYYY-MM-DD.jsonl`, `<data>/orders.jsonl`, `<data>/ground_truth/gt-<run_id>.jsonl`.
"""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from .catalog import Catalog
from .config import FRICTION_IDS, SynthConfig
from .groundtruth import GroundTruthWriter, ground_truth_row
from .journeys import Ctx, run_journey
from .model import API, ASSET, BEACON, PAGE, Client, Outcome, Req, Resp
from .personas import build_signer, make_client
from .signer import Signer
from .site import SiteSim, is_asset_path

try:
    import orjson

    def _dumps(obj: Any) -> str:
        return orjson.dumps(obj).decode()

except ImportError:  # pragma: no cover - orjson is an optional speed-up

    def _dumps(obj: Any) -> str:
        return json.dumps(obj, separators=(",", ":"))


HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
ASSET_DEST = {".css": "style", ".js": "script", ".mjs": "script"}
BASE_DATE = "2026-11-01"
FLUSH_EVERY = 60_000


@lru_cache(maxsize=1 << 16)
def _iso_second(sec: int) -> str:
    return datetime.fromtimestamp(sec, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S")


def iso_ms(t: float) -> str:
    sec = int(t)
    return f"{_iso_second(sec)}.{int((t - sec) * 1000):03d}Z"


def _request_id(rng: random.Random) -> str:
    h = f"{rng.getrandbits(128):032x}"
    return f"{h[:8]}-{h[8:12]}-4{h[13:16]}-8{h[17:20]}-{h[20:]}"


@dataclass
class SessionResult:
    lines: list[tuple[float, str]] = field(default_factory=list)
    orders: list[dict[str, Any]] = field(default_factory=list)
    outcome: Outcome = field(default_factory=lambda: Outcome(task=""))
    client: Client | None = None
    start: float = 0.0
    toggles_active: list[str] = field(default_factory=list)


class Simulator:
    def __init__(self, cfg: SynthConfig, catalog: Catalog, toggles_at: Callable[[float], dict[str, bool]],
                 signer: Signer | None = None, synth_meta: bool = True) -> None:  # fmt: skip
        self.cfg = cfg
        self.cat = catalog
        self.toggles_at = toggles_at
        self.site = SiteSim(cfg, catalog, toggles_at)
        self.signer = signer or build_signer(cfg.raw)
        self.host = cfg.host
        self.synth_meta = synth_meta

    def _record(self, c: Client, req: Req, resp: Resp, t: float, sig: dict[str, str] | None, event: str) -> dict[str, Any]:
        h = c.headers
        asset = req.kind == ASSET or is_asset_path(req.path)
        if req.kind == PAGE:
            accept = HTML_ACCEPT if h["html"] else "*/*"
        elif req.kind == API or req.kind == BEACON:
            accept = "application/json, text/plain, */*" if c.js else "*/*"
        else:
            accept = "text/css,*/*;q=0.1" if req.path.endswith(".css") else "image/avif,image/webp,image/*,*/*;q=0.8"
        sec = bool(h["sec_fetch"])
        dest = "document"
        if req.kind == API or req.kind == BEACON:
            dest = "empty"
        elif asset:
            dest = next((v for ext, v in ASSET_DEST.items() if req.path.endswith(ext)), "image")
        meta = dict(resp.meta)
        if self.synth_meta:
            meta["synth_session_id"] = c.synth_session_id
        mode = "navigate" if req.kind == PAGE else ("no-cors" if req.kind == ASSET else "cors")
        return {
            "ts": iso_ms(t), "request_id": _request_id(c.rng), "method": req.method, "host": self.host,
            "path": req.path, "query": req.query, "status": resp.status, "bytes_out": resp.bytes_out,
            "duration_ms": resp.duration_ms, "ip_hash": c.ip_hash, "ip_prefix": c.ip_prefix, "user_agent": c.ua,
            "referer": f"{self.host}{req.referer}" if req.referer else None, "accept": accept,
            "accept_language": h["accept_language"] or None, "sec_ch_ua": (h["sec_ch_ua"] or None) if c.js else None,
            "sec_fetch_site": (("same-origin" if req.referer else "none") if sec else None),
            "sec_fetch_mode": mode if sec else None, "sec_fetch_dest": dest if sec else None,
            "signature": sig["signature"] if sig else None, "signature_input": sig["signature-input"] if sig else None,
            "signature_agent": sig["signature-agent"] if sig else None,
            "cookie_sid_hash": c.cookie_hash if c.has_cookie else None, "is_asset": asset, "event_type": event, "meta": meta,
        }  # fmt: skip

    def simulate(self, index: int, start: float, persona: str, seed: int, session_id: str) -> SessionResult:
        spec = self.cfg.personas[persona]
        rng = random.Random(seed * 1_000_003 + index)
        client = make_client(persona, spec, rng, session_id)
        out = Outcome(task="")
        ctx = Ctx(client, self.cat, self.cfg.raw, self.toggles_at, out)
        gen = run_journey(ctx)
        res = SessionResult(client=client, start=start)
        res.toggles_active = [f for f, on in self.toggles_at(start).items() if on]
        lines = res.lines
        t = start
        site = self.site
        try:
            req = next(gen)
            while True:
                t += req.think
                if req.kind == PAGE:
                    client.pages_seen += 1
                sig = None
                if client.signer_mode and req.kind in (PAGE, API) and req.sign:
                    sig = self.signer.sign(req.method, self.host, req.path, req.query, int(t) - rng.randrange(0, 3),
                                           mode=client.signer_mode).as_dict()  # fmt: skip
                resp = site.respond(client, req, t)
                lines.append((t, _dumps(self._record(client, req, resp, t, sig, "request"))))
                if req.kind == API and req.path == "/api/checkout" and resp.status == 201:
                    self._order(res, client, req, resp, t)
                if client.keeps_cookies and not client.has_cookie:
                    client.has_cookie = True
                if req.kind == PAGE:
                    for offset, extra in site.page_extras(client, req, resp, {}):
                        te = t + resp.duration_ms / 1000 + offset
                        er = site.respond(client, extra, te)
                        event = "beacon" if extra.kind == BEACON else "request"
                        lines.append((te, _dumps(self._record(client, extra, er, te, None, event))))
                t += resp.duration_ms / 1000
                ctx.t = t
                req = gen.send(resp)
        except StopIteration as stop:
            res.outcome = stop.value
        return res

    def _order(self, res: SessionResult, client: Client, req: Req, resp: Resp, t: float) -> None:
        sid = client.cookie_hash if client.has_cookie else client.session_hash
        res.orders.append({"order_id": resp.data["order_id"], "session_cookie_id": sid, "cart_value": resp.data["cart_value"],
                           "ts": iso_ms(t), "payment_method": resp.data["payment_method"]})  # fmt: skip
        ometa = {k: resp.data[k] for k in ("order_id", "cart_value", "payment_method")}
        if self.synth_meta:
            ometa["synth_session_id"] = client.synth_session_id
        order_line = self._record(client, req, Resp(201, None, {}, 0, 0, ometa), t, None, "order")
        res.lines.append((t + 0.0005, _dumps(order_line)))


# ---- planning and driver -----------------------------------------------------------------------------------------

def plan_sessions(cfg: SynthConfig, n: int, days: float, seed: int, start_date: str) -> list[tuple[float, str]]:
    """(start_ts, persona) for every session, sorted by start. Deterministic in `seed`."""
    rng = np.random.default_rng(seed)
    names, shares = cfg.shares()
    persona_idx = rng.choice(len(names), size=n, p=shares)
    base = datetime.fromisoformat(start_date).replace(tzinfo=UTC).timestamp()
    horizon = max(1.0, days) * 86400
    hours_w = np.array(cfg.raw["diurnal_weight"]["human"], dtype=float)
    hours_w /= hours_w.sum()
    starts = np.empty(n)
    ndays = max(1, int(np.ceil(days)))
    for i, name in enumerate(names):
        mask = persona_idx == i
        k = int(mask.sum())
        if not k:
            continue
        d = rng.integers(0, ndays, size=k)
        h = rng.choice(24, size=k, p=hours_w) if cfg.personas[name]["behavior"] == "human" else rng.integers(0, 24, size=k)
        starts[mask] = d * 86400 + h * 3600 + rng.random(k) * 3600
    starts = np.minimum(starts, horizon - 1)
    order = np.argsort(starts, kind="stable")
    return [(base + float(starts[j]), names[persona_idx[j]]) for j in order]


@dataclass
class OfflineResult:
    run_id: str
    sessions: int
    lines: int
    orders: int
    files: list[Path]
    seconds: float
    ground_truth: Path
    persona_counts: dict[str, int] = field(default_factory=dict)
    converted: dict[str, int] = field(default_factory=dict)


class _DayWriter:
    def __init__(self, out_dir: Path, force: bool) -> None:
        self.out_dir, self.force = out_dir, force
        self.files: dict[str, Path] = {}
        self._cur: tuple[str, Any] | None = None
        self.lines = 0

    def _handle(self, day: str) -> Any:
        if self._cur and self._cur[0] == day:
            return self._cur[1]
        if self._cur:
            self._cur[1].close()
        path = self.out_dir / f"access-{day}.jsonl"
        mode = "ab" if day in self.files else "wb"
        if mode == "wb" and path.exists() and not self.force:
            raise FileExistsError(f"{path} exists (use --force to overwrite)")
        self.files[day] = path
        fh = path.open(mode)
        self._cur = (day, fh)
        return fh

    def write(self, records: list[tuple[float, str]]) -> None:
        buf: list[str] = []
        cur_day = ""
        for ts, line in records:
            day = _iso_second(int(ts))[:10]
            if day != cur_day:
                if buf:
                    self._handle(cur_day).write(("\n".join(buf) + "\n").encode())
                    buf = []
                cur_day = day
            buf.append(line)
        if buf:
            self._handle(cur_day).write(("\n".join(buf) + "\n").encode())
        self.lines += len(records)

    def close(self) -> None:
        if self._cur:
            self._cur[1].close()
            self._cur = None


def data_dir_for(out: Path) -> Path:
    return out.parent if out.name == "logs" else out


def toggle_changes(before: dict[str, bool], after: dict[str, bool]) -> list[str]:
    return [f for f in FRICTION_IDS if before[f] != after[f]]


def _config_change_line(cfg: SynthConfig, ts: float, seed: int, after: dict[str, bool], changed: list[str]) -> str:
    return _dumps({
        "ts": iso_ms(ts), "request_id": _request_id(random.Random(seed ^ 0x5EED)), "method": "POST", "host": cfg.host,
        "path": "/api/admin/friction", "query": "", "status": 200, "bytes_out": 0, "duration_ms": 0, "ip_hash": None,
        "ip_prefix": None, "user_agent": None, "referer": None, "accept": None, "accept_language": None,
        "sec_ch_ua": None, "sec_fetch_site": None, "sec_fetch_mode": None, "sec_fetch_dest": None, "signature": None,
        "signature_input": None, "signature_agent": None, "cookie_sid_hash": None, "is_asset": False,
        "event_type": "config_change", "meta": {"toggles": after, "changed": changed},
    })  # fmt: skip


def run_offline(
    *, sessions: int, days: float, seed: int, out: Path, start_date: str = BASE_DATE, state: str = "before",
    toggles: set[str] | None = None, run_id: str | None = None, force: bool = False, cfg: SynthConfig | None = None,
    switch_after_days: float | None = None, catalog: Catalog | None = None,
) -> OfflineResult:  # fmt: skip
    """Generate `sessions` sessions over `days` days. With `switch_after_days` the Before state flips to the After state."""
    t0 = time.perf_counter()
    cfg = cfg or SynthConfig.load()
    catalog = catalog or Catalog.load()
    run_id = run_id or f"run-{seed}"
    out.mkdir(parents=True, exist_ok=True)
    data_dir = data_dir_for(out)
    base = datetime.fromisoformat(start_date).replace(tzinfo=UTC).timestamp()

    if toggles is not None:
        before_state = after_state = {f: f in toggles for f in FRICTION_IDS}
    elif switch_after_days is not None:
        before_state, after_state = cfg.state("before"), cfg.state("after")
    else:
        before_state = after_state = cfg.state(state)
    switch_ts = base + switch_after_days * 86400 if switch_after_days is not None else float("inf")

    def toggles_at(ts: float) -> dict[str, bool]:
        return before_state if ts < switch_ts else after_state

    sim = Simulator(cfg, catalog, toggles_at)
    plan = plan_sessions(cfg, sessions, days, seed, start_date)
    writer = _DayWriter(out, force)
    gt = GroundTruthWriter(data_dir / "ground_truth" / f"gt-{run_id}.jsonl")
    orders_path = data_dir / "orders.jsonl"
    if orders_path.exists() and not force:
        raise FileExistsError(f"{orders_path} exists (use --force to overwrite)")
    orders_fh = orders_path.open("w", encoding="utf-8")
    buffer: list[tuple[float, str]] = []
    if switch_after_days is not None:
        buffer.append((switch_ts, _config_change_line(cfg, switch_ts, seed, after_state, toggle_changes(before_state, after_state))))

    persona_counts: dict[str, int] = {}
    converted: dict[str, int] = {}
    total_orders = 0
    for i, (start, persona) in enumerate(plan):
        res = sim.simulate(i, start, persona, seed, f"syn-{seed:x}-{i:07x}")
        buffer.extend(res.lines)
        for o in res.orders:
            orders_fh.write(_dumps(o) + "\n")
        total_orders += len(res.orders)
        gt.add(ground_truth_row(run_id, res, cfg))
        persona_counts[persona] = persona_counts.get(persona, 0) + 1
        if res.outcome.converted:
            converted[persona] = converted.get(persona, 0) + 1
        if len(buffer) >= FLUSH_EVERY:
            # every later session starts at or after `start`, so records before it are final
            buffer.sort(key=lambda x: x[0])
            cut = _bisect(buffer, start)
            writer.write(buffer[:cut])
            del buffer[:cut]
    buffer.sort(key=lambda x: x[0])
    writer.write(buffer)
    writer.close()
    orders_fh.close()
    gt_path = gt.close()
    return OfflineResult(run_id, sessions, writer.lines, total_orders, sorted(writer.files.values()),
                         time.perf_counter() - t0, gt_path, persona_counts, converted)  # fmt: skip


def _bisect(buf: list[tuple[float, str]], ts: float) -> int:
    lo, hi = 0, len(buf)
    while lo < hi:
        mid = (lo + hi) // 2
        if buf[mid][0] < ts:
            lo = mid + 1
        else:
            hi = mid
    return lo
