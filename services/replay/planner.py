"""Planners choose the next action from the set the journey currently allows.

The deterministic planner takes the first allowed action (the list is priority-ordered). The OpenAI planner asks the model
to pick one of the allowed actions; the answer is validated, so the model can reorder or stop the journey but can never
invent an action, a URL or a payload. Any failure (no answer, invalid action, token budget) falls back to the deterministic
choice for the rest of the replay.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from agentlens.diagnosis.llm import redact

from .llm import ReplayLLM

SYSTEM = (
    "You steer a shopping test agent on a demo store. Choose exactly one next action from the allowed list. "
    'Reply as JSON: {"action": "<one of allowed>", "reason": "<short>"}. Never propose actions that are not allowed.'
)


@dataclass
class Decision:
    action: str
    reason: str = ""
    source: str = "deterministic"


class Planner(Protocol):
    name: str

    @property
    def tokens_used(self) -> int: ...

    def decide(self, goal: str, state: dict[str, Any], allowed: list[str]) -> Decision: ...


class DeterministicPlanner:
    name = "deterministic"
    tokens_used = property(lambda self: 0)

    def decide(self, goal: str, state: dict[str, Any], allowed: list[str]) -> Decision:
        return Decision(allowed[0], "first allowed action by priority")


class OpenAIPlanner:
    name = "openai"

    def __init__(self, llm: ReplayLLM, *, max_tokens: int) -> None:
        self.llm = llm
        self.max_tokens = max_tokens
        self.fallback_reason: str | None = None
        self._det = DeterministicPlanner()

    @property
    def tokens_used(self) -> int:
        return self.llm.tokens_used

    def decide(self, goal: str, state: dict[str, Any], allowed: list[str]) -> Decision:
        if len(allowed) == 1:
            return Decision(allowed[0], "only one valid action", "forced")
        if self.fallback_reason:
            return self._det.decide(goal, state, allowed)
        if self.llm.tokens_used >= self.max_tokens:
            self.fallback_reason = f"token budget of {self.max_tokens} reached"
            return self._det.decide(goal, state, allowed)
        user = redact(f"Goal: {goal}\nState: {state}\nAllowed: {allowed}")
        out = self.llm.chat_json(SYSTEM, user)
        action = out.get("action") if out else None
        if action not in allowed:
            self.fallback_reason = "model gave no valid action" if out is None else f"model proposed {action!r}"
            return self._det.decide(goal, state, allowed)
        return Decision(str(action), str(out.get("reason", ""))[:160] if out else "", "openai")


def make_planner(llm: ReplayLLM | None, max_tokens: int) -> Planner:
    return OpenAIPlanner(llm, max_tokens=max_tokens) if llm is not None else DeterministicPlanner()
