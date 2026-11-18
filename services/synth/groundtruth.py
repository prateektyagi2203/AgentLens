"""Ground truth writer (PRD 17.5): `<data>/ground_truth/gt-<run_id>.jsonl`. Read only by services/api/eval."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .config import SynthConfig

if TYPE_CHECKING:
    from .offline import SessionResult


def ground_truth_row(run_id: str, res: SessionResult, cfg: SynthConfig) -> dict[str, Any]:
    client = res.client
    assert client is not None
    spec = client.spec
    entry = client.ua_entry
    human = spec["behavior"] == "human"
    return {
        "run_id": run_id,
        "synthetic_session_id": client.synth_session_id,
        "persona": client.persona,
        "expected_tier": spec["tier"],
        "operator": entry.get("operator") or spec.get("operator"),
        "agent_name": entry.get("name") or spec.get("agent_name"),
        "agent_class": "human" if human else (entry.get("class") or spec.get("agent_class")),
        "task": res.outcome.task,
        "toggles_active": res.toggles_active,
        "blocker_hit": res.outcome.blocker,
        "stage_of_failure": res.outcome.stage_of_failure,
        "converted": res.outcome.converted,
    }


class GroundTruthWriter:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._fh = path.open("w", encoding="utf-8")

    def add(self, row: dict[str, Any]) -> None:
        self._fh.write(json.dumps(row, separators=(",", ":")) + "\n")

    def close(self) -> Path:
        self._fh.close()
        return self.path
