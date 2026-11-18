"""Minimal OpenAI chat client for the replay planner / vision check, with token accounting and an injectable transport.

Follows ADR-001: the OpenAI path is used only when `AGENTLENS_LLM_PROVIDER=openai` and `OPENAI_API_KEY` is set; otherwise the
replay uses the deterministic planner. Prompts only ever carry the task text, test data and redacted page summaries.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

import httpx
from agentlens.diagnosis.llm import get_provider

DEFAULT_BASE = "https://api.openai.com/v1"


class ReplayLLM:
    def __init__(
        self, api_key: str, model: str, *, base_url: str = DEFAULT_BASE, client: httpx.Client | None = None,
        timeout_s: float = 30.0,
    ) -> None:  # fmt: skip
        self.api_key, self.model, self.base_url = api_key, model, base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=timeout_s)
        self.tokens_used = 0
        self.calls = 0

    @classmethod
    def from_env(cls, name: str | None = None) -> ReplayLLM | None:
        if get_provider(name).name != "openai":
            return None
        return cls(os.environ["OPENAI_API_KEY"].strip(), os.getenv("AGENTLENS_LLM_MODEL", "gpt-4o-mini"))

    def chat_json(self, system: str, user: str, *, image: Path | None = None, max_tokens: int = 200) -> dict[str, Any] | None:
        content: Any = user
        if image is not None:
            b64 = base64.b64encode(image.read_bytes()).decode()
            content = [{"type": "text", "text": user},
                       {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "low"}}]  # fmt: skip
        body = {
            "model": self.model, "temperature": 0, "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
        }  # fmt: skip
        self.calls += 1
        try:
            r = self._client.post(f"{self.base_url}/chat/completions", json=body,
                                  headers={"Authorization": f"Bearer {self.api_key}"})  # fmt: skip
            r.raise_for_status()
            data = r.json()
            self.tokens_used += int((data.get("usage") or {}).get("total_tokens") or 0)
            parsed = json.loads(data["choices"][0]["message"]["content"])
        except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
