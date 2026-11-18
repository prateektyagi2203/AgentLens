"""Persona instantiation: draws a concrete client (IP, UA, cookie behaviour, header profile) from config/synth.yaml."""

from __future__ import annotations

import hashlib
import random
import uuid
from typing import Any

from agentlens import settings

from .model import Client
from .signer import Signer

RESIDENTIAL = ("49.36", "106.208", "117.99", "223.176", "182.69", "103.211", "152.58", "27.60", "157.45", "42.106")
PLAIN_CHROME = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    '"Chromium";v="131", "Not_A Brand";v="24"',
)  # a stealth headless agent hides its HeadlessChrome hint behind this


def sha(text: str) -> str:
    return hashlib.sha256((settings.ip_salt() + text).encode()).hexdigest()


def _ip(rng: random.Random, pool: str) -> str:
    prefix = rng.choice(RESIDENTIAL) if pool == "residential" else pool.split(":", 1)[1]
    return f"{prefix}.{rng.randrange(0, 256)}.{rng.randrange(1, 255)}"


def _weighted(rng: random.Random, entries: list[dict[str, Any]]) -> dict[str, Any]:
    if len(entries) == 1:
        return entries[0]
    return rng.choices(entries, weights=[float(e.get("weight", 1)) for e in entries])[0]


def make_client(name: str, spec: dict[str, Any], rng: random.Random, synth_session_id: str) -> Client:
    entry = _weighted(rng, spec["uas"])
    ua, sec_ch_ua = str(entry["ua"]), entry.get("sec_ch_ua")
    stealth = bool(spec.get("stealth")) and rng.random() < float(spec["stealth"])
    if stealth:
        ua, sec_ch_ua = PLAIN_CHROME
    ip = _ip(rng, str(spec["ip_pool"]))
    accept_mode = str(spec.get("accept", "html"))
    mixed_html = accept_mode == "html" or (accept_mode == "mixed" and rng.random() < 0.5)
    js = bool(spec.get("js"))
    sec_fetch = rng.random() < float(spec.get("sec_fetch", 0))
    human = spec["behavior"] == "human"
    lang = None
    if human:
        lang = "en-IN,en;q=0.9" if rng.random() < 0.8 else "en-US,en;q=0.9,hi;q=0.8"
    elif name == "signed_agent" or (js and rng.random() < 0.5):
        lang = "en-US,en;q=0.9"
    cookie_uuid = str(uuid.UUID(int=rng.getrandbits(128), version=4))
    client = Client(
        persona=name, spec=spec, ip=ip, ua=ua, ua_entry=dict(entry),
        headers={"sec_ch_ua": sec_ch_ua or "", "accept_language": lang or "", "html": "1" if mixed_html else ""},
        cookie_uuid=cookie_uuid, keeps_cookies=rng.random() < float(spec.get("keeps_cookies", 0)),
        rng=rng, synth_session_id=synth_session_id, js=js, beacon=js and rng.random() < float(spec.get("beacon", 0)),
        assets=bool(spec.get("assets")), cached_assets=rng.random() < float(spec.get("cached_assets", 0)),
        stealth=stealth,
    )  # fmt: skip
    client.headers["sec_fetch"] = "1" if sec_fetch else ""
    client.ip_hash = sha(ip)
    client.ip_prefix = ".".join(ip.split(".")[:3]) + ".0/24"
    client.cookie_hash = sha(cookie_uuid)
    client.session_hash = sha(f"ipua:{ip}|{ua}")
    signs = spec.get("signs")
    client.signer_mode = None if not signs else ("valid" if signs == "valid" else rng.choice(["wrong_key", "unknown_key"]))
    return client


def build_signer(cfg_raw: dict[str, Any]) -> Signer:
    sig = cfg_raw["signature"]
    return Signer(str(cfg_raw["operator_origin"]), label=sig["label"], expires_s=int(sig["expires_s"]),
                  agent_header=sig["agent_header"])  # fmt: skip
