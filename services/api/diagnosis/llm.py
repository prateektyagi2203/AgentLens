"""Optional LLM layer behind one provider interface (ADR-001): `mock` (default, deterministic, offline) and `openai`.

Used for two things only, never for the numbers: classifying sessions the rules left unexplained (B99 candidates), and
a two-sentence tailored explanation for recommendations. Rules-only mode (no key, no network) is the baseline and is
always what `agentlens run-all` does unless `AGENTLENS_LLM_PROVIDER=openai` and `OPENAI_API_KEY` are set.

Privacy: a session summary contains only method, normalised path (ids, emails and digit runs masked), status, error code,
duration and page type of up to N requests, plus the agent class. No IPs, user agents, cookies, query strings or order
values leave the machine. Verdicts are validated with pydantic and cached on a hash of the summary + model.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field, ValidationError

from .. import settings

CODE_TO_BLOCKER = {
    "BOT_CHALLENGE": "B01", "CAPTCHA_REQUIRED": "B02", "PINCODE_REQUIRED": "B05", "AUTH_REQUIRED": "B06",
    "OUT_OF_STOCK": "B08", "PHONE_FORMAT": "B10", "COD_OTP_REQUIRED": "B11", "RATE_LIMITED": "B12",
}  # fmt: skip
VALID_BLOCKERS = {f"B{i:02d}" for i in range(1, 17)}

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
_LONG_ID = re.compile(r"(?<=/)(?:[A-Z]{2,4}-[0-9A-F]{6,}|[0-9a-f]{12,}|\d{5,})(?=/|$)")


class Verdict(BaseModel):
    blocker_id: str = Field(pattern=r"^B(0[1-9]|1[0-6]|99)$")
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(max_length=500)
    suggested_new_blocker: str | None = Field(default=None, max_length=200)


@dataclass
class SessionSummary:
    session_id: str
    agent_class: str
    max_stage: str | None
    requests: list[dict[str, Any]] = field(default_factory=list)

    def prompt(self) -> str:
        lines = [
            f"{r['method']} {r['path']} -> {r['status']}"
            + (f" {r['error_code']}" if r["error_code"] else "")
            + (f" ({r['duration_ms']} ms)" if r["duration_ms"] and r["duration_ms"] > 1000 else "")
            for r in self.requests
        ]
        return (
            f"AI shopping agent session ({self.agent_class}), deepest funnel stage {self.max_stage or 'none'}, "
            f"did not convert. Requests in order:\n" + "\n".join(lines)
        )


def redact(text: str) -> str:
    text = _EMAIL.sub("{email}", text)
    text = _LONG_ID.sub("{id}", text)
    return _PHONE.sub("{phone}", text)


def redact_path(path: str) -> str:
    return redact(path.split("?", 1)[0])


class LLMProvider(Protocol):
    name: str
    model: str

    def classify(self, summary: SessionSummary) -> Verdict | None: ...

    def explain(self, blocker_id: str, blocker_name: str, evidence: str) -> str | None: ...


class MockProvider:
    """Deterministic stand-in: reads the last explicit error code or status in the summary. No network, no randomness."""

    name = "mock"
    model = "mock-1"

    def classify(self, summary: SessionSummary) -> Verdict | None:
        for r in reversed(summary.requests):
            code = r.get("error_code")
            if code in CODE_TO_BLOCKER:
                return Verdict(blocker_id=CODE_TO_BLOCKER[code], confidence=0.65,
                               rationale=f"Last failing call returned {r['status']} {code}.")  # fmt: skip
        last = summary.requests[-1] if summary.requests else None
        if last and last["status"] == 404:
            return Verdict(blocker_id="B16", confidence=0.65, rationale="Session ended on a 404.")
        if last and last["status"] and last["status"] >= 500:
            return Verdict(blocker_id="B99", confidence=0.3, rationale="Session ended on a server error with no code.",
                           suggested_new_blocker="Unexplained 5xx errors")  # fmt: skip
        return Verdict(blocker_id="B99", confidence=0.2, rationale="No explicit failure in the session.")

    def explain(self, blocker_id: str, blocker_name: str, evidence: str) -> str | None:
        return None


SYSTEM_PROMPT = (
    "You diagnose why an AI shopping agent failed on an ecommerce site. Choose the single most likely blocker id from: "
    "B01 bot wall, B02 captcha at checkout, B03 JS-only product content, B04 missing structured data, B05 pincode wall, "
    "B06 login/OTP wall, B07 interstitial overlay, B08 out-of-stock dead end, B09 image-only size guide, B10 checkout "
    "validation, B11 COD/payment step, B12 rate limited, B13 slow response, B14 robots.txt disallow, B15 price mismatch, "
    "B16 broken link, or B99 unknown. Reply with JSON only: "
    '{"blocker_id": "...", "confidence": 0..1, "rationale": "one sentence", "suggested_new_blocker": null or "short name"}.'
)


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str, model: str, *, client: httpx.Client | None = None, base_url: str = "https://api.openai.com/v1") -> None:
        self.api_key, self.model, self.base_url = api_key, model, base_url
        self._client = client

    def _chat(self, system: str, user: str, *, json_mode: bool) -> str | None:
        body: dict[str, Any] = {
            "model": self.model, "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }  # fmt: skip
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            client = self._client or httpx.Client(timeout=30)
            resp = client.post(f"{self.base_url}/chat/completions", json=body, headers={"Authorization": f"Bearer {self.api_key}"})
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return str(content) if content else None
        except (httpx.HTTPError, KeyError, IndexError, ValueError):
            return None

    def classify(self, summary: SessionSummary) -> Verdict | None:
        raw = self._chat(SYSTEM_PROMPT, summary.prompt(), json_mode=True)
        if raw is None:
            return None
        try:
            return Verdict.model_validate(json.loads(raw))
        except (ValidationError, ValueError):
            return None

    def explain(self, blocker_id: str, blocker_name: str, evidence: str) -> str | None:
        raw = self._chat(
            "Write exactly two plain sentences for a store owner: what blocked AI shopping agents and why the fix helps. "
            "Cite the evidence numbers given. No markdown.",
            f"Blocker {blocker_id} ({blocker_name}). Evidence: {evidence}", json_mode=False,
        )  # fmt: skip
        return raw.strip() if raw else None


def get_provider(name: str | None = None) -> LLMProvider:
    """`mock` unless AGENTLENS_LLM_PROVIDER=openai *and* a key is present (otherwise falls back to mock)."""
    name = (name or os.getenv("AGENTLENS_LLM_PROVIDER") or "mock").lower()
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if name == "openai" and key:
        return OpenAIProvider(key, os.getenv("AGENTLENS_LLM_MODEL", "gpt-4o-mini"))
    return MockProvider()


class Cache:
    """Append-only JSONL cache keyed by sha256(provider|model|prompt)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or settings.data_dir() / "llm_cache.jsonl"
        self._mem: dict[str, Any] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self._mem[rec["k"]] = rec["v"]

    @staticmethod
    def key(provider: LLMProvider, prompt: str) -> str:
        return hashlib.sha256(f"{provider.name}|{provider.model}|{prompt}".encode()).hexdigest()

    def get(self, k: str) -> Any | None:
        return self._mem.get(k)

    def put(self, k: str, v: Any) -> None:
        self._mem[k] = v
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"k": k, "v": v}) + "\n")


def classify_cached(provider: LLMProvider, cache: Cache | None, summary: SessionSummary) -> tuple[Verdict | None, bool]:
    """(verdict, was_cached). Mock results are never cached (they are free and deterministic)."""
    prompt = summary.prompt()
    use_cache = cache is not None and provider.name != "mock"
    if use_cache:
        assert cache is not None
        hit = cache.get(Cache.key(provider, prompt))
        if hit is not None:
            try:
                return Verdict.model_validate(hit), True
            except ValidationError:
                pass
    verdict = provider.classify(summary)
    if verdict is not None and use_cache:
        assert cache is not None
        cache.put(Cache.key(provider, prompt), verdict.model_dump())
    return verdict, False


def estimate_tokens(prompts: list[str]) -> int:
    return sum(len(SYSTEM_PROMPT) + len(p) for p in prompts) // 4
