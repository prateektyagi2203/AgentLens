"""Synth configuration (config/synth.yaml) and the toggle states used by scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentlens import settings

FRICTION_IDS = tuple(f"F{i:02d}" for i in range(1, 17))


@dataclass
class SynthConfig:
    raw: dict[str, Any]

    @classmethod
    def load(cls, override: dict[str, Any] | None = None) -> SynthConfig:
        raw = settings.load_yaml("synth")
        if override:
            raw = {**raw, **override}
        return cls(raw)

    @property
    def host(self) -> str:
        return str(self.raw["host"])

    @property
    def personas(self) -> dict[str, dict[str, Any]]:
        return dict(self.raw["personas"])

    def state(self, name: str) -> dict[str, bool]:
        active = set(self.raw["states"][name])
        return {f: f in active for f in FRICTION_IDS}

    def shares(self) -> tuple[list[str], list[float]]:
        names = list(self.personas)
        total = sum(float(self.personas[n]["share"]) for n in names)
        return names, [float(self.personas[n]["share"]) / total for n in names]
