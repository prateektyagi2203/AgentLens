"""Agent Readiness Report generator (PRD 19): Markdown, PDF and a PNG of the one-pager.

* `generate_report(con, fmt, out_dir) -> list[Path]`: writes `agent-readiness-report.{md,pdf,png}` (fmt = md|pdf|png|all).
* `build_report(con, fmt, filters) -> (bytes, media_type)`: the same content in memory, for the API download.

PDF/PNG render the HTML page through Playwright's Chromium (`RendererUnavailable` if it is not installed).
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from .data import collect
from .markdown import executive_summary, render_markdown
from .page import render_html
from .render import RendererUnavailable, chromium_ready, render_pdf_png

FORMATS = ("md", "pdf", "png")
MEDIA_TYPES = {"md": "text/markdown", "pdf": "application/pdf", "png": "image/png"}
BASENAME = "agent-readiness-report"


def build_report(
    con: duckdb.DuckDBPyConnection, fmt: str, filters: dict[str, str | None] | None = None
) -> tuple[bytes, str]:
    """Return `(body, media_type)` for `fmt` in md|pdf|png. Raises ValueError for any other format."""
    if fmt not in FORMATS:
        raise ValueError(f"unsupported report format {fmt!r}; use one of {', '.join(FORMATS)}")
    data = collect(con, filters)
    if fmt == "md":
        return render_markdown(data).encode("utf-8"), MEDIA_TYPES["md"]
    pdf, png = render_pdf_png(render_html(data), pdf=fmt == "pdf", png=fmt == "png")
    body = pdf if fmt == "pdf" else png
    assert body is not None
    return body, MEDIA_TYPES[fmt]


def generate_report(
    con: duckdb.DuckDBPyConnection, fmt: str, out_dir: Path | str, filters: dict[str, str | None] | None = None
) -> list[Path]:
    """Write the report file(s) into `out_dir` (created if needed) and return their paths. `fmt` may be `all`."""
    wanted = list(FORMATS) if fmt == "all" else [fmt]
    for f in wanted:
        if f not in FORMATS:
            raise ValueError(f"unsupported report format {f!r}; use md, pdf, png or all")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    data = collect(con, filters)
    paths: list[Path] = []
    if "md" in wanted:
        p = out / f"{BASENAME}.md"
        p.write_text(render_markdown(data), encoding="utf-8")
        paths.append(p)
    if "pdf" in wanted or "png" in wanted:
        pdf, png = render_pdf_png(render_html(data), pdf="pdf" in wanted, png="png" in wanted)
        for ext, blob in (("pdf", pdf), ("png", png)):
            if blob is not None:
                p = out / f"{BASENAME}.{ext}"
                p.write_bytes(blob)
                paths.append(p)
    return paths


__all__ = [
    "BASENAME", "FORMATS", "RendererUnavailable", "build_report", "chromium_ready", "collect", "executive_summary",
    "generate_report", "render_html", "render_markdown",
]  # fmt: skip
