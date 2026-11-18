"""Shared types between journeys (what a client does), the simulated store and the live HTTP driver."""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass, field
from typing import Any

PAGE, API, ASSET, BEACON = "page", "api", "asset", "beacon"


@dataclass(slots=True)
class Req:
    method: str
    path: str
    query: str = ""
    kind: str = PAGE
    body: dict[str, Any] | None = None
    think: float = 0.0  # seconds to wait after the previous response before sending
    referer: str | None = None
    sign: bool = True  # whether a signing persona signs this request


@dataclass(slots=True)
class Resp:
    status: int
    error_code: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 50
    bytes_out: int = 0
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Outcome:
    task: str
    converted: bool = False
    blocker: str | None = None  # blocker id (B01..B15) that ended the journey
    stage_of_failure: str | None = None  # funnel stage that failed (S1..S8)
    order_id: str | None = None
    order_value: float | None = None


@dataclass
class ClientState:
    """Server-side state the store keeps per client (cookie, or ip+ua when the client drops cookies)."""

    pincode_ok: bool = False
    otp_verified: bool = False
    cod_otp_verified: bool = False
    captcha_answer: str | None = None
    cart: list[dict[str, Any]] = field(default_factory=list)
    hits: deque[float] = field(default_factory=deque)  # request times for the F12 rate limiter


@dataclass
class Client:
    persona: str
    spec: dict[str, Any]
    ip: str
    ua: str
    ua_entry: dict[str, Any]
    headers: dict[str, str]
    cookie_uuid: str
    keeps_cookies: bool
    has_cookie: bool = False
    state: ClientState = field(default_factory=ClientState)
    rng: random.Random = field(default_factory=random.Random)
    synth_session_id: str = ""
    signer_mode: str | None = None  # None | "valid" | "forged"
    js: bool = False
    beacon: bool = False
    assets: bool = False
    cached_assets: bool = False
    pages_seen: int = 0
    last_page: str | None = None
    ip_hash: str = ""
    ip_prefix: str = ""
    cookie_hash: str = ""
    session_hash: str = ""  # hash the store would log for orders when there is no cookie
    stealth: bool = False
