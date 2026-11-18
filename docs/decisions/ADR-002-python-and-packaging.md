# ADR-002: Python 3.11, single `agentlens` package over three service folders
Date: 2026-11-18
Status: Accepted
## Context
PRD asks for Python 3.12; the build machine has 3.11. The PRD repo layout has `services/api`, `services/replay`, `services/synth`.
## Decision
Target Python >=3.11 (no 3.12-only syntax). `pyproject.toml` maps the three folders to `agentlens`, `agentlens.replay` and `agentlens.synth`, so the CLI is one `agentlens` command and imports are stable.
## Alternatives considered
Installing 3.12 via uv (unneeded); top-level packages named `api`, `replay`, `synth` (generic, collision-prone).
## Consequences
CI runs 3.11. Moving to 3.12 later needs only a version bump.
