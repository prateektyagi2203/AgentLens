"""Central settings and YAML config loading. Paths resolve from the repo root so every entrypoint agrees."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")


def config_dir() -> Path:
    return Path(os.getenv("AGENTLENS_CONFIG_DIR", REPO_ROOT / "config"))


def data_dir() -> Path:
    raw = os.getenv("AGENTLENS_DATA_DIR", "./data")
    p = Path(raw)
    return p if p.is_absolute() else (REPO_ROOT / p).resolve()


def db_path() -> Path:
    return Path(os.getenv("AGENTLENS_DB_PATH", data_dir() / "agentlens.duckdb"))


def logs_dir() -> Path:
    return data_dir() / "logs"


def load_yaml(name: str) -> dict[str, Any]:
    """Load config/<name>.yaml. Not cached so edits made through the Settings API apply immediately."""
    with open(config_dir() / f"{name}.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def save_yaml(name: str, content: dict[str, Any]) -> None:
    with open(config_dir() / f"{name}.yaml", "w", encoding="utf-8") as fh:
        yaml.safe_dump(content, fh, sort_keys=False)


@lru_cache(maxsize=1)
def ip_salt() -> str:
    return os.getenv("AGENTLENS_IP_SALT", "change-me")


def demo_mode() -> bool:
    return os.getenv("DEMO_MODE", "0") == "1"
