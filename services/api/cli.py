"""`agentlens` command line entrypoint. Subcommands are registered by each milestone."""

from __future__ import annotations

from pathlib import Path

import typer

from . import __version__, db, pipeline, settings
from .replay import cli as replay_cli
from .report import cli as report_cli
from .synth.cli import synth_app

app = typer.Typer(help="AgentLens: agent analytics for ecommerce.", no_args_is_help=True)
app.add_typer(synth_app, name="synth")
replay_cli.register(app)
report_cli.register(app)


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


def _run(
    steps: list[str] | None, source: Path | None = None, fmt: str = "jsonl", extra: dict[str, object] | None = None
) -> None:
    con = db.connect()
    try:
        params: dict[str, object] = {"source": str(source) if source else None, "fmt": fmt}
        params.update({k: v for k, v in (extra or {}).items() if v is not None})
        res = pipeline.run_steps(con, steps, params)
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


@app.command()
def funnel() -> None:
    """Classify requests into funnel stages; compute max_stage and funnel aggregates."""
    _run(["funnel"])


@app.command()
def diagnose(
    site_url: str = typer.Option(None, "--site-url", help="Store base URL for site checks (default: AGENTLENS_SITE_URL)."),
    llm: str = typer.Option(None, "--llm", help="mock | openai | off (default: AGENTLENS_LLM_PROVIDER or mock)."),
) -> None:
    """Apply blocker rules B01-B16 (+B99 via optional LLM) to failed agent sessions."""
    _run(["diagnose"], extra={"site_url": site_url, "llm_provider": llm})


@app.command("site-checks")
def site_checks(
    site_url: str = typer.Option(None, "--site-url", help="Store base URL (default: AGENTLENS_SITE_URL)."),
    as_of: str = typer.Option(
        None, "--as-of", help="Record the probe as of this UTC time (ISO 8601). For replaying a store's history, e.g. the demo."
    ),
) -> None:
    """Probe the live store (robots.txt, llms.txt, JSON-LD, SSR price, size guide, captcha). Skips when offline."""
    import os
    from datetime import UTC, datetime

    from .diagnosis.engine import load_config
    from .diagnosis.sitechecks import run_site_checks

    cfg = load_config()["site_checks"]
    url = site_url or os.getenv("AGENTLENS_SITE_URL") or cfg.get("base_url") or ""
    now = datetime.fromisoformat(as_of.replace("Z", "+00:00")).astimezone(UTC) if as_of else None
    con = db.connect()
    try:
        res = run_site_checks(
            con, url, timeout_s=float(cfg.get("timeout_s", 5)), pdp_sample=int(cfg.get("pdp_sample", 5)), now=now
        )
    finally:
        con.close()
    typer.echo(res)


@app.command()
def impact() -> None:
    """Estimate rupee impact per blocker (PRD 14)."""
    _run(["impact"])


@app.command()
def recommend() -> None:
    """Rank fixes by impact/effort."""
    _run(["recommend"])


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


@app.command("eval-diagnosis")
def eval_diagnosis(
    logs: Path = typer.Option(None, help="Log directory holding the generator's lines (default: <data>/logs)."),
    run_id: str = typer.Option(None, help="Ground-truth run id (default: all runs)."),
    golden: bool = typer.Option(False, "--golden", help="Generate the deterministic 2,000-session golden set and evaluate it."),
) -> None:
    """Compare diagnosis with synthetic ground truth (SC4: precision >= 85%, recall >= 80%)."""
    from .eval import evaluate_diagnosis, format_diagnosis_report, write_report

    if golden:
        from .eval.golden import run_golden

        ev = run_golden()
    else:
        con = db.connect()
        try:
            ev = evaluate_diagnosis(con, logs, run_id)
        finally:
            con.close()
    typer.echo(format_diagnosis_report(ev))
    typer.echo(f"report: {write_report(ev, label='golden' if golden else '')}")
    if not ev.passed:
        raise typer.Exit(1)


@app.command("eval")
def eval_all(
    logs: Path = typer.Option(None, help="Log directory holding the generator's lines (default: <data>/logs)."),
    run_id: str = typer.Option(None, help="Ground-truth run id (default: all runs)."),
) -> None:
    """Run identification + diagnosis evaluation and write <data>/eval/latest.json for the dashboard."""
    from .eval.latest import build_latest, write_latest

    con = db.connect()
    try:
        doc = build_latest(con, logs, run_id)
    finally:
        con.close()
    typer.echo(f"wrote {write_latest(doc)}")


@app.command("export-snapshot")
def export_snapshot_cmd(
    out: Path | None = typer.Option(None, "--out", help="Output directory (default: apps/dashboard/public/demo, which the dashboard serves as /demo)."),
    force: bool = typer.Option(False, "--force", help="Replace --out even if it is not an earlier snapshot."),
) -> None:
    """Write the static public-demo snapshot (docs/api-contract.md section 4) from the current database."""
    from .snapshot import SnapshotError, export_snapshot

    out = (settings.REPO_ROOT / "apps" / "dashboard" / "public" / "demo") if out is None else out.resolve()
    try:
        res = export_snapshot(out, force=force)
    except SnapshotError as exc:
        typer.echo(f"export-snapshot failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(
        f"snapshot: {res['files']} files, {res['bytes'] / 1e6:.1f} MB, {res['sessions']} sessions, {res['agents']} agents, "
        f"{res['replays']} replays ({res['screenshots']} screenshots), eval={'yes' if res['eval'] else 'no'}"
    )
    typer.echo(f"before window {res['before']['from']}..{res['before']['to']}; written to {res['out']}")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind address."),
    port: int = typer.Option(8100, help="Port (the dashboard defaults to http://localhost:8100/api)."),
    reload: bool = typer.Option(False, help="Auto-reload on code changes (development)."),
) -> None:
    """Serve the dashboard API. Stop it before running other commands: DuckDB allows a single writer process."""
    import uvicorn

    uvicorn.run("agentlens.main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
