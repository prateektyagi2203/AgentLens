"""Settings (GET/PUT), latest evaluation and the report download."""

from __future__ import annotations

import copy
import importlib
import json
import math
from typing import Any

import duckdb
from fastapi import APIRouter, Body, Depends
from fastapi.responses import Response

from .. import settings
from . import analytics as an
from .deps import ApiError, Filters, filters_dep, get_read, not_found

router = APIRouter()

NUM = (int, float)
SUSPICION_WEIGHTS = (
    "no_beacon_with_browser_ua", "no_assets", "headless_hint", "missing_sec_fetch", "regular_timing", "high_velocity",
    "deep_link_cart_rush", "atypical_accept", "invalid_signature",
)  # fmt: skip


def current_settings() -> dict[str, Any]:
    imp, ident, diag = settings.load_yaml("impact"), settings.load_yaml("identification"), settings.load_yaml("diagnosis")
    ctx = an.load_ctx()
    thr = diag.get("thresholds") or {}
    sig, sus, ses = ident.get("signature") or {}, ident.get("suspicion") or {}, ident.get("sessions") or {}
    weights = sus.get("weights") or {}
    rr = imp.get("recoverable_rate") or {}
    ew = imp.get("effort_weights") or {}
    return {
        "impact": {
            "recoverable_rate": {"low": rr.get("low", 0.4), "base": rr.get("base", 0.6), "high": rr.get("high", 0.8)},
            "p_stage_band": imp.get("p_stage_band", 0.2), "default_aov_inr": imp.get("default_aov_inr", 2200),
            "agent_vs_human_factor": imp.get("agent_vs_human_factor", 1.0), "min_sample": imp.get("min_sample", 30),
            "effort_weights": {"S": ew.get("S", 1), "M": ew.get("M", 2), "L": ew.get("L", 4)},
        },
        "identification": {
            "signature": {"clock_skew_s": sig.get("clock_skew_s", 60), "key_cache_ttl_s": sig.get("key_cache_ttl_s", 3600),
                          "offline_mode": bool(sig.get("offline_mode", False))},
            "suspicion": {"threshold": sus.get("threshold", 60), "page_velocity_per_min": sus.get("page_velocity_per_min", 15),
                          "weights": {k: weights.get(k, 0) for k in SUSPICION_WEIGHTS}},
            "sessions": {"timeout_min_human": ses.get("timeout_min_human", 30), "timeout_min_agent": ses.get("timeout_min_agent", 10)},
        },
        "thresholds": {"slow_response_ms": thr.get("slow_ms", 5000), "significance_min_sessions": ctx.min_sessions},
    }  # fmt: skip


def _get(doc: Any, path: str) -> Any:
    for part in path.split("."):
        if not isinstance(doc, dict) or part not in doc:
            return None
        doc = doc[part]
    return doc


def validate(body: Any) -> dict[str, str]:
    e: dict[str, str] = {}
    if not isinstance(body, dict):
        return {"": "Expected a Settings object"}

    def rng(key: str, lo: float, hi: float, integer: bool = False) -> None:
        v = _get(body, key)
        if isinstance(v, bool) or not isinstance(v, NUM) or not math.isfinite(v):
            e[key] = "Enter a number"
        elif integer and int(v) != v:
            e[key] = "Must be a whole number"
        elif v < lo or v > hi:
            e[key] = f"Must be between {lo:g} and {hi:g}"

    for k in ("low", "base", "high"):
        rng(f"impact.recoverable_rate.{k}", 0, 1)
    lo, base, hi = (_get(body, f"impact.recoverable_rate.{k}") for k in ("low", "base", "high"))
    if "impact.recoverable_rate.low" not in e and "impact.recoverable_rate.base" not in e and lo > base:
        e["impact.recoverable_rate.low"] = "Low must not exceed base"
    if "impact.recoverable_rate.base" not in e and "impact.recoverable_rate.high" not in e and base > hi:
        e["impact.recoverable_rate.high"] = "High must not be below base"
    rng("impact.p_stage_band", 0, 0.9)
    rng("impact.default_aov_inr", 1, 10_000_000)
    rng("impact.agent_vs_human_factor", 0.1, 5)
    rng("impact.min_sample", 1, 100_000, True)
    for k in ("S", "M", "L"):
        rng(f"impact.effort_weights.{k}", 0.5, 100)
    s, m, big = (_get(body, f"impact.effort_weights.{k}") for k in ("S", "M", "L"))
    if "impact.effort_weights.S" not in e and "impact.effort_weights.M" not in e and s > m:
        e["impact.effort_weights.M"] = "M must be at least S"
    if "impact.effort_weights.M" not in e and "impact.effort_weights.L" not in e and m > big:
        e["impact.effort_weights.L"] = "L must be at least M"
    rng("identification.signature.clock_skew_s", 0, 600, True)
    rng("identification.signature.key_cache_ttl_s", 60, 86_400, True)
    if not isinstance(_get(body, "identification.signature.offline_mode"), bool):
        e["identification.signature.offline_mode"] = "Must be true or false"
    rng("identification.suspicion.threshold", 1, 100)
    rng("identification.suspicion.page_velocity_per_min", 1, 600)
    for k in SUSPICION_WEIGHTS:
        rng(f"identification.suspicion.weights.{k}", 0, 100)
    rng("identification.sessions.timeout_min_human", 1, 240, True)
    rng("identification.sessions.timeout_min_agent", 1, 240, True)
    rng("thresholds.slow_response_ms", 100, 60_000, True)
    rng("thresholds.significance_min_sessions", 10, 100_000, True)
    return e


def _merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in patch.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _write_if_changed(name: str, new: dict[str, Any]) -> None:
    if settings.load_yaml(name) != new:
        settings.save_yaml(name, new)


@router.get("/settings")
def get_settings() -> dict[str, Any]:
    return current_settings()


@router.put("/settings")
def put_settings(body: Any = Body(default=None)) -> dict[str, Any]:
    errors = validate(body)
    if errors:
        raise ApiError(422, "validation_error", "Invalid settings", errors)
    imp = body["impact"]
    ident = body["identification"]
    thr = body["thresholds"]
    _write_if_changed("impact", _merge(settings.load_yaml("impact"), imp))
    _write_if_changed(
        "identification",
        _merge(settings.load_yaml("identification"), {
            "signature": ident["signature"],
            "suspicion": {k: ident["suspicion"][k] for k in ("threshold", "page_velocity_per_min", "weights")},
            "sessions": ident["sessions"],
        }),
    )  # fmt: skip
    _write_if_changed(
        "diagnosis",
        _merge(settings.load_yaml("diagnosis"), {"thresholds": {
            "slow_ms": thr["slow_response_ms"], "significance_min_sessions": thr["significance_min_sessions"],
        }}),
    )  # fmt: skip
    an.clear_yaml_cache()
    return current_settings()


# ---------------------------------------------------------------- eval
@router.get("/eval/latest")
def eval_latest() -> dict[str, Any]:
    path = settings.data_dir() / "eval" / "latest.json"
    if not path.is_file():
        raise not_found("No evaluation has been run yet (run `agentlens eval`)")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise not_found(f"Latest evaluation is unreadable: {exc}") from exc
    return doc


# ---------------------------------------------------------------- report
MEDIA = {"md": "text/markdown", "pdf": "application/pdf", "png": "image/png"}


@router.get("/report")
def report(
    format: str = "md", f: Filters = Depends(filters_dep), cur: duckdb.DuckDBPyConnection = Depends(get_read)
) -> Response:  # fmt: skip
    if format not in MEDIA:
        raise ApiError(400, "bad_request", f"Unsupported report format '{format}' (use md, pdf or png)")
    try:
        mod = importlib.import_module("agentlens.report")
    except ImportError:
        mod = None
    if mod is None or not hasattr(mod, "build_report"):
        raise ApiError(501, "not_implemented", "The report generator is not available in this build")
    filters = {"from": f.from_, "to": f.to, "segment": f.segment, "operator": f.operator, "agent_class": f.agent_class}
    data, media_type = mod.build_report(cur, format, filters)
    return Response(
        content=data, media_type=media_type or MEDIA[format],
        headers={"Content-Disposition": f'attachment; filename="agent-readiness-report.{format}"'},
    )  # fmt: skip
