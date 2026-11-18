"""Dashboard API routers (contract: docs/api-contract.md). `router` is mounted under `/api` by `agentlens.main`."""

from __future__ import annotations

from fastapi import APIRouter

from . import agents, blockers, core, ops, replays, runs, sessions

router = APIRouter()
for module in (core, agents, blockers, sessions, replays, ops, runs):
    router.include_router(module.router)

__all__ = ["router"]
