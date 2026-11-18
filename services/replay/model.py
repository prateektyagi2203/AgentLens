"""Result types shared by the fetch and browser replay agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

CONFIRMED = "confirmed"
NOT_REPRODUCED = "not_reproduced"
INCONCLUSIVE = "inconclusive"
VERDICTS = (CONFIRMED, NOT_REPRODUCED, INCONCLUSIVE)


def api_verdict(verdict: str | None) -> str | None:
    """The dashboard contract (docs/api-contract.md) says `not_confirmed` where the PRD says `not_reproduced`."""
    return "not_confirmed" if verdict == NOT_REPRODUCED else verdict


@dataclass
class StepRecord:
    n: int
    action: str
    method: str | None
    url: str
    status: int | None
    duration_ms: int
    note: str
    screenshot: str | None = None          # file name inside the evidence dir
    blocker_id: str | None = None          # hypothesis this step produced evidence for
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_api(self, replay_id: str) -> dict[str, Any]:
        """ReplayStep per apps/dashboard/lib/types.ts, plus `blocker_id` and `evidence`."""
        return {
            "n": self.n, "action": self.action, "method": self.method, "url": self.url, "status": self.status,
            "duration_ms": self.duration_ms, "note": self.note,
            "screenshot_url": f"/api/replays/{replay_id}/screenshots/{self.screenshot}" if self.screenshot else None,
            "blocker_id": self.blocker_id, "evidence": self.evidence,
        }  # fmt: skip


@dataclass
class Signal:
    """One observation about a blocker hypothesis: present (the friction was seen) or absent (it was probed and not seen)."""

    blocker_id: str
    present: bool
    detail: str
    step_n: int
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReplayResult:
    replay_id: str
    blocker_id: str | None
    mode: str
    verdict: str
    explanation: str
    started_at: datetime
    finished_at: datetime
    steps: list[StepRecord] = field(default_factory=list)
    network_log: list[dict[str, Any]] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)
    task: str = ""
    task_completed: bool = False
    order_id: str | None = None
    workarounds: list[str] = field(default_factory=list)
    user_agent: str = ""
    signed_requests: bool = False
    evidence_dir: str | None = None
    source_session_id: str | None = None
    planner: str = "deterministic"
    llm_tokens: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def blockers_observed(self) -> list[str]:
        return sorted({s.blocker_id for s in self.signals if s.present})

    def steps_payload(self) -> dict[str, Any]:
        """Shape stored in `replays.steps_json` (agreed with the API router)."""
        return {
            "verdict": api_verdict(self.verdict), "user_agent": self.user_agent, "signed_requests": self.signed_requests,
            "steps": [s.to_api(self.replay_id) for s in self.steps], "network_log": self.network_log,
            "task": self.task, "task_completed": self.task_completed, "order_id": self.order_id,
            "blockers_observed": self.blockers_observed, "workarounds": self.workarounds, "planner": self.planner,
            "llm_tokens": self.llm_tokens, "notes": self.notes,
        }  # fmt: skip
