"""Replay configuration (config/replay.yaml) and the host allow-list (PRD 13.3 RP1, 25 PS5)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from agentlens import settings

DEFAULT_TASK = "buy a size-M blue shirt under 1500 INR, deliver to pincode 560001"
DEFAULT_UA = "AgentLens-Replay/1.0 (+https://github.com/prateektyagi2203/AgentLens)"
UA_TOKEN = "AgentLens-Replay"


class HostNotAllowed(PermissionError):
    """Raised before any network I/O when a URL is outside the allow-list."""


class RobotsDisallowed(PermissionError):
    """Raised when robots.txt forbids the replay agent from fetching a path."""


@dataclass(frozen=True)
class AllowList:
    """Exact `host:port` entries; an entry without a port matches that host on the default ports (none, 80, 443)."""

    entries: tuple[str, ...]

    @staticmethod
    def _split(entry: str) -> tuple[str, int | None]:
        parts = urlsplit(entry if "//" in entry else f"//{entry}")
        return (parts.hostname or "").lower(), parts.port

    def allows(self, url: str) -> bool:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
            return False
        host, port = parts.hostname.lower(), parts.port
        for entry in self.entries:
            e_host, e_port = self._split(entry)
            if host != e_host:
                continue
            if e_port is None and port in (None, 80, 443):
                return True
            if e_port is not None and port == e_port:
                return True
        return False

    def check(self, url: str) -> None:
        if not self.allows(url):
            raise HostNotAllowed(f"{urlsplit(url).netloc or url!r} is not in the replay allow-list {list(self.entries)}")


@dataclass
class ReplayConfig:
    allowed_hosts: list[str] = field(default_factory=lambda: ["localhost:3100", "127.0.0.1:3100"])
    top_n_blockers: int = 5
    sessions_per_blocker: int = 3
    max_replays_per_run: int = 50
    step_pause_s: float = 2.0
    user_agent: str = DEFAULT_UA
    sign_requests: bool = False
    default_task: str = DEFAULT_TASK
    base_url: str = "http://localhost:3100"
    default_mode: str = "fetch"
    auto_browser: bool = True              # blockers that need a real DOM (B07) are replayed in browser mode
    respect_robots: bool = True
    request_timeout_s: float = 20.0
    max_steps: int = 30                    # hard cap on planner steps per replay
    max_seconds: float = 180.0             # wall-clock cap per replay
    max_tokens: int = 6000                 # LLM token cap per replay (prompt + completion)
    slow_pdp_ms: int = 2000                # B13: PDP slower than this
    bypass_test_walls: bool = True         # use the store's documented test OTP to look past a login wall
    test_otp: str = "123456"
    load_probe_requests: int = 25          # B12 burst size
    load_probe_pause_s: float = 0.05
    load_probes: bool = False              # allow the B12 burst against non-local hosts (needs the site owner's consent)
    vision: bool = False                   # OpenAI screenshot check in browser mode
    test_profile: dict[str, str] = field(default_factory=lambda: {
        "name": "Test Shopper", "phone": "9876543210", "address": "12 Test Street, Indiranagar, Bengaluru",
        "pincode": "560001",
    })  # fmt: skip

    @property
    def allow_list(self) -> AllowList:
        return AllowList(tuple(self.allowed_hosts))

    @classmethod
    def load(cls, **overrides: Any) -> ReplayConfig:
        raw = settings.load_yaml("replay")
        known = set(cls.__dataclass_fields__)
        cfg = cls(**{k: v for k, v in raw.items() if k in known})
        public = os.getenv("PUBLIC_STORE_HOST", "").strip()
        if public and public not in cfg.allowed_hosts:
            cfg.allowed_hosts.append(public)
        for k, v in overrides.items():
            if v is not None:
                setattr(cfg, k, v)
        return cfg


def is_local_host(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local")
