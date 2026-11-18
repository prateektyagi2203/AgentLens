"""`agentlens report` command (registered from agentlens.cli)."""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from agentlens import db, settings


def _utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def register(app: typer.Typer) -> None:
    @app.command("report")
    def report(
        fmt: str = typer.Option("all", "--format", help="md | pdf | png | all."),
        out: Path = typer.Option(None, "--out", help="Output directory (default: <data>/reports)."),
        from_: str = typer.Option(None, "--from", help="Window start, YYYY-MM-DD (default: all data)."),
        to: str = typer.Option(None, "--to", help="Window end, YYYY-MM-DD."),
        segment: str = typer.Option(None, help="all_agents | verified | declared | suspected."),
        operator: str = typer.Option(None, help="Only this operator."),
        agent_class: str = typer.Option(None, help="Only this agent class."),
    ) -> None:
        """Write the Agent Readiness Report (Markdown, PDF, and a PNG of the one-pager)."""
        from . import RendererUnavailable, generate_report

        _utf8()
        con = db.connect()
        try:
            try:
                paths = generate_report(
                    con, fmt, out or settings.data_dir() / "reports",
                    {"from": from_, "to": to, "segment": segment, "operator": operator, "agent_class": agent_class},
                )  # fmt: skip
            except ValueError as exc:
                typer.echo(str(exc), err=True)
                raise typer.Exit(2) from exc
            except RendererUnavailable as exc:
                typer.echo(str(exc), err=True)
                raise typer.Exit(1) from exc
        finally:
            con.close()
        for p in paths:
            typer.echo(f"wrote {p}")

    @app.command("before-after")
    def before_after_cmd(
        segment: str = typer.Option("all_agents", help="Segment to compare."),
    ) -> None:
        """Print the Before/After comparison around the first fix annotation (the dashboard's /compare numbers)."""
        from agentlens.compare import before_after

        from .inr import inr, pct

        _utf8()
        con = db.connect()
        try:
            res = before_after(con, segment=segment)
        finally:
            con.close()
        if res is None:
            typer.echo("No config_change / marked_fixed annotation with data on both sides; nothing to compare.")
            raise typer.Exit(1)
        h = res["headline"]
        typer.echo(res["label"])
        typer.echo(f"agent sessions      {h['sessions_before']:>10,} -> {h['sessions_after']:,}")
        typer.echo(f"agent conversion    {pct(h['conversion_before']):>10} -> {pct(h['conversion_after'])}"
                   f"  ({h['conversion_pp']:+.1f} pp)")  # fmt: skip
        typer.echo(f"agent revenue       {inr(h['agent_revenue_before_inr']):>10} -> {inr(h['agent_revenue_after_inr'])}")
        typer.echo(f"risk / month (base) {inr(h['risk_before_inr']):>10} -> {inr(h['risk_after_inr'])}")
        typer.echo(f"significance        {res['compare']['significance']['note']}")
        for d in res["blocker_deltas"][:5]:
            typer.echo(f"  {d['blocker_id']:<4} {d['name'][:34]:<34} {inr(d['risk_before_inr']):>9} -> {inr(d['risk_after_inr'])}")
