"""PRD 12.6: analysis packages must never touch ground truth or the generator's session link."""

from __future__ import annotations

from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[2] / "services" / "api"
FORBIDDEN = ("ground_truth", "synth_session_id")
GUARDED = [
    "ingest", "identify", "sessions", "funnel", "diagnosis", "impact", "recommend", "routers", "pipeline.py", "clientkey.py",
]


def _files() -> list[Path]:
    out: list[Path] = []
    for name in GUARDED:
        p = API / name
        if not p.exists() and (API / f"{name}.py").exists():
            p = API / f"{name}.py"
        if p.is_file():
            out.append(p)
        elif p.is_dir():
            out += [f for f in p.rglob("*") if f.is_file() and f.suffix in (".py", ".sql", ".json", ".yaml")]
    return out


def test_guarded_packages_exist():
    names = {f.parent.name for f in _files()}
    assert {"ingest", "identify", "sessions"} <= names


@pytest.mark.parametrize("path", _files(), ids=lambda p: str(p.relative_to(API)))
def test_no_ground_truth_access(path: Path):
    text = path.read_text(encoding="utf-8")
    hits = [w for w in FORBIDDEN if w in text]
    assert not hits, f"{path.name} references {hits}"


def test_only_eval_package_reads_ground_truth():
    readers = {
        f.relative_to(API).as_posix()
        for f in API.rglob("*.py")
        if "ground_truth" in f.read_text(encoding="utf-8")
    }
    # snapshot.py only names the key to refuse it in exported files; it never reads the table.
    assert all(r.startswith("eval/") or r in ("db.py", "snapshot.py") for r in readers), readers
