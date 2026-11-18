"""Report generator: INR formatting, Markdown content, and a PDF/PNG smoke test (skipped without Chromium)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from agentlens.identify.constants import HONEST_LIMITATION
from agentlens.report import build_report, chromium_ready, generate_report
from agentlens.report.data import collect
from agentlens.report.inr import inr, inr_full, pct


@pytest.mark.parametrize(
    ("value", "text"),
    [(0, "₹0"), (82_400, "₹82,400"), (99_999, "₹99,999"), (126_000, "₹1.3 L"), (1_260_000, "₹12.6 L"),
     (12_000_000, "₹1.2 Cr"), (111_980, "₹1.1 L")],
)  # fmt: skip
def test_inr_uses_lakh_and_crore(value: float, text: str) -> None:
    assert inr(value) == text


def test_inr_full_groups_the_indian_way() -> None:
    assert inr_full(111_980) == "₹1,11,980"
    assert inr_full(12_34_56_789) == "₹12,34,56,789"
    assert pct(0.0602) == "6.0%"


@pytest.fixture(scope="module")
def data(ba_db: Any) -> dict[str, Any]:
    return collect(ba_db, None)


def test_markdown_has_numbers_inr_and_the_honest_limitation(ba_db: Any) -> None:
    body, media = build_report(ba_db, "md", {})
    md = body.decode("utf-8")
    assert media == "text/markdown"
    for heading in ("# Agent Readiness Report", "## Executive summary", "## Top blockers", "## Recommendations",
                    "## Before and after", "## Honest limitations"):  # fmt: skip
        assert heading in md
    assert HONEST_LIMITATION in md
    assert "₹" in md and " L" in md  # lakh formatting in the headline
    assert "B06" in md and "B05" in md
    assert "statistically significant" in md


def test_markdown_numbers_match_the_comparison(ba_db: Any, data: dict[str, Any]) -> None:
    md = build_report(ba_db, "md", {})[0].decode("utf-8")
    ba = data["before_after"]
    assert ba is not None
    h = ba["headline"]
    assert pct(h["conversion_before"]) in md and pct(h["conversion_after"]) in md
    assert inr(h["agent_revenue_after_inr"]) in md
    top = data["blockers"][0]
    assert inr(top["risk_base"]) in md


def test_report_without_data_still_renders(tmp_path: Path) -> None:
    from agentlens import db

    con = db.connect(tmp_path / "empty.duckdb")
    try:
        md = build_report(con, "md", {})[0].decode("utf-8")
    finally:
        con.close()
    assert "# Agent Readiness Report" in md and HONEST_LIMITATION in md


def test_unsupported_format_is_rejected(ba_db: Any, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsupported"):
        build_report(ba_db, "docx", {})
    with pytest.raises(ValueError, match="unsupported"):
        generate_report(ba_db, "docx", tmp_path)


def test_generate_md_writes_the_file(ba_db: Any, tmp_path: Path) -> None:
    paths = generate_report(ba_db, "md", tmp_path / "out")
    assert [p.name for p in paths] == ["agent-readiness-report.md"]
    assert paths[0].read_text(encoding="utf-8").startswith("# Agent Readiness Report")


@pytest.mark.skipif(not chromium_ready(), reason="Playwright Chromium is not installed")
def test_pdf_and_png_are_created(ba_db: Any, tmp_path: Path) -> None:
    paths = generate_report(ba_db, "all", tmp_path)
    by = {p.suffix: p for p in paths}
    assert set(by) == {".md", ".pdf", ".png"}
    assert by[".pdf"].read_bytes()[:5] == b"%PDF-" and by[".pdf"].stat().st_size > 10_000
    assert by[".png"].read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" and by[".png"].stat().st_size > 10_000
    body, media = build_report(ba_db, "pdf", {})
    assert media == "application/pdf" and body[:5] == b"%PDF-"
