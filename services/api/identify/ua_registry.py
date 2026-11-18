"""Tier 2 (Declared): match user agents and Signature-Agent origins against config/agents.yaml (PRD 11.2)."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from .. import settings

CLASS_BROWSING = "browsing_agent"
CLASS_INTERNAL = "internal"
CLASS_ROBOTS_ONLY = "robots_token_only"
CRAWLER_CLASSES = ("search_crawler", "training_crawler")


@dataclass(frozen=True)
class AgentEntry:
    operator_key: str
    operator: str  # display name, stored in requests.operator
    agent_name: str
    agent_class: str
    tokens: tuple[str, ...]


@dataclass
class UARegistry:
    entries: list[AgentEntry]
    signature_agents: dict[str, str]  # origin -> operator key
    operators: dict[str, str]  # operator key -> display name
    ip_ranges: dict[str, list[ipaddress.IPv4Network | ipaddress.IPv6Network]]
    robots_tokens: dict[str, str] = field(default_factory=dict)  # robots token -> operator display
    _tokens: list[tuple[str, AgentEntry]] = field(default_factory=list)

    def __post_init__(self) -> None:
        pairs = [(t.lower(), e) for e in self.entries for t in e.tokens]
        self._tokens = sorted(pairs, key=lambda p: -len(p[0]))  # longest token wins

    @classmethod
    def from_config(cls, cfg: dict[str, Any] | None = None) -> UARegistry:
        cfg = cfg if cfg is not None else settings.load_yaml("agents")
        entries: list[AgentEntry] = []
        sig_agents: dict[str, str] = {}
        operators: dict[str, str] = {}
        ranges: dict[str, list[ipaddress.IPv4Network | ipaddress.IPv6Network]] = {}
        robots: dict[str, str] = {}
        for key, op in (cfg.get("operators") or {}).items():
            display = op.get("display_name", key)
            operators[key] = display
            for origin in op.get("signature_agents") or []:
                sig_agents[_origin(origin)] = key
            ranges[key] = [ipaddress.ip_network(r, strict=False) for r in op.get("ip_ranges") or []]
            for ag in op.get("agents") or []:
                if ag.get("robots_token"):
                    robots[str(ag["robots_token"]).lower()] = display
                toks = tuple(ag.get("ua_tokens") or [])
                if toks and ag.get("class") != CLASS_ROBOTS_ONLY:
                    entries.append(AgentEntry(key, display, ag["name"], ag["class"], toks))
        return cls(entries, sig_agents, operators, ranges, robots)

    def match(self, user_agent: str | None) -> AgentEntry | None:
        if not user_agent:
            return None
        ua = user_agent.lower()
        for token, entry in self._tokens:
            if token in ua:
                return entry
        return None

    def operator_for_origin(self, origin: str | None) -> tuple[str, str] | None:
        """(operator key, display name) for a Signature-Agent origin, if configured."""
        if not origin:
            return None
        key = self.signature_agents.get(_origin(origin))
        return (key, self.operators[key]) if key else None

    def default_agent_for(self, operator_key: str) -> AgentEntry | None:
        """The operator's browsing agent if it has one, else its first agent: used for signed requests with no UA token."""
        cands = [e for e in self.entries if e.operator_key == operator_key]
        return next((e for e in cands if e.agent_class == CLASS_BROWSING), cands[0] if cands else None)

    def ip_match(self, operator_key: str, ip_prefix: str | None) -> bool:
        nets = self.ip_ranges.get(operator_key) or []
        if not nets or not ip_prefix:
            return False
        try:
            candidate = ipaddress.ip_network(ip_prefix, strict=False)
        except ValueError:
            return False
        return any(n.version == candidate.version and n.overlaps(candidate) for n in nets)


def _origin(url: str) -> str:
    parts = urlsplit(url if "://" in url else f"https://{url}")
    return f"{parts.scheme}://{parts.netloc}".lower()


def declared_confidence(ip_match: bool) -> float:
    return 0.9 if ip_match else 0.7
