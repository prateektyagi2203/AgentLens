"""`agentlens` command line entrypoint. Subcommands are registered by each milestone."""

from __future__ import annotations

from pathlib import Path

import typer

from . import __version__, db, pipeline, settings
from .synth.cli import synth_app

app = typer.Typer(help="AgentLens: agent analytics for ecommerce.", no_args_is_help=True)
app.add_typer(synth_app, name="synth")


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(__version__)


@app.command("init-db")
def init_db() -> None:
    """Create the DuckDB file and apply the schema."""
    con = db.connect()
    con.close()
    typer.echo(f"Database ready at {settings.db_path()}")


def _run(steps: list[str] | None, source: Path | None = None, fmt: str = "jsonl") -> None:
    con = db.connect()
    try:
        res = pipeline.run_steps(con, steps, {"source": str(source) if source else None, "fmt": fmt})
    finally:
        con.close()
    for s in res.steps:
        detail = s.get("counts") or s.get("error", "")
        typer.echo(f"{s['name']:<10} {s['status']:<8} {s['seconds']:>8.2f}s  {detail}")
    typer.echo(f"run {res.run_id}: {res.status}")
    if not res.ok:
        raise typer.Exit(1)


@app.command()
def ingest(
    source: Path = typer.Option(None, help="Log file or directory (default: <data>/logs)."),
    fmt: str = typer.Option("jsonl", "--format", help="jsonl | nginx_combined."),
) -> None:
    """Load logs incrementally into DuckDB (idempotent; bad lines go to ingest_errors)."""
    _run(["ingest"], source, fmt)


@app.command()
def identify() -> None:
    """Classify requests: Verified (Web Bot Auth), Declared (UA registry), Suspected (behaviour), Human."""
    _run(["identify"])


@app.command()
def sessionize() -> None:
    """Group requests into sessions with the strongest identity and link orders."""
    _run(["sessionize"])


@app.command("run-all")
def run_all(
    source: Path = typer.Option(None, help="Log file or directory (default: <data>/logs)."),
    fmt: str = typer.Option("jsonl", "--format", help="jsonl | nginx_combined."),
) -> None:
    """Run every registered pipeline step in order."""
    _run(None, source, fmt)


@app.command("eval-identification")
def eval_identification(
    logs: Path = typer.Option(None, help="Log directory holding the generator's lines (default: <data>/logs)."),
    run_id: str = typer.Option(None, help="Ground-truth run id (default: all runs)."),
) -> None:
    """Compare identification with synthetic ground truth (SC1-SC3)."""
    from .eval import evaluate_identification, format_report

    con = db.connect()
    try:
        ev = evaluate_identification(con, logs, run_id)
    finally:
        con.close()
    typer.echo(format_report(ev))
    if not ev.passed:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
