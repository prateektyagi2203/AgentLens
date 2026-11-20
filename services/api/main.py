"""FastAPI app: the dashboard routers live under /api (see docs/api-contract.md); /health stays as an alias."""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__, settings
from .routers import router
from .routers.deps import ApiError

log = logging.getLogger("agentlens.api")

app = FastAPI(title="AgentLens API", version=__version__)
# Extra browser origins (comma separated), e.g. https://agentlens.ptlabs.in for a public deployment.
_extra_origins = [o.strip().rstrip("/") for o in os.getenv("AGENTLENS_CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3101", "http://127.0.0.1:3101", *_extra_origins],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)
app.include_router(router, prefix="/api")


@app.middleware("http")
async def read_only_in_demo(request: Request, call_next: Any) -> Any:
    # Public deployments run with DEMO_MODE=1: no pipeline/LLM/replay runs, annotations or settings edits.
    if settings.demo_mode() and request.method not in ("GET", "HEAD", "OPTIONS"):
        return _error(403, "demo_mode", "This public demo is read-only")
    return await call_next(request)

CODES = {400: "bad_request", 404: "not_found", 405: "method_not_allowed", 409: "run_in_progress", 501: "not_implemented"}


def _error(status: int, code: str, message: str, fields: dict[str, str] | None = None) -> JSONResponse:
    body: dict[str, Any] = {"code": code, "message": message}
    if fields:
        body["fields"] = fields
    return JSONResponse({"error": body}, status_code=status)


@app.exception_handler(ApiError)
async def api_error(_: Request, exc: ApiError) -> JSONResponse:
    return _error(exc.status, exc.code, exc.message, exc.fields)


@app.exception_handler(RequestValidationError)
async def invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
    fields: dict[str, str] = {}
    for err in exc.errors():
        loc = [str(p) for p in err["loc"] if p not in ("query", "body", "path")]
        fields.setdefault(".".join(loc) or "body", str(err["msg"]))
    return _error(422, "validation_error", "Invalid request", fields)


@app.exception_handler(StarletteHTTPException)
async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    return _error(exc.status_code, CODES.get(exc.status_code, "error"), str(exc.detail))


@app.exception_handler(Exception)
async def unexpected(_: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error", exc_info=exc)
    return _error(500, "internal_error", "Internal server error")


@app.get("/health", include_in_schema=False)
def health_alias() -> dict[str, str]:
    return {"status": "ok", "version": __version__}
