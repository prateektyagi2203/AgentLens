"""FastAPI app. Routers for the dashboard are added in M4; M0 only exposes /health."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__

app = FastAPI(title="AgentLens API", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3101", "http://127.0.0.1:3101"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
@app.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}
