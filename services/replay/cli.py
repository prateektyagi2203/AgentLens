"""`agentlens replay` and `agentlens replay-all` commands (registered from agentlens.cli)."""

from __future__ import annotations

import sys

import typer
from agentlens import db

from .config import HostNotAllowed, ReplayConfig


def _utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def register(app: typer.Typer) -> None:
    @app.command("replay")
    def replay(
        blocker: str = typer.Option(None, "--blocker", help="Blocker hypothesis to test, e.g. B05 (default: free run)."),
        task: str = typer.Option(None, help="Shopping task (default: replay.yaml default_task)."),
        mode: str = typer.Option(None, help="fetch (HTTP, no browser) or browser (Playwright). Default from replay.yaml."),
        base_url: str = typer.Option(None, "--base-url", help="Store to replay against (default: replay.yaml base_url)."),
        pause: float = typer.Option(None, help="Seconds between requests (default: replay.yaml step_pause_s)."),
        vision: bool = typer.Option(False, "--vision", help="Browser mode: let OpenAI look at screenshots (needs a key)."),
        sign: bool = typer.Option(False, "--sign", help="Sign requests with the test-operator Web Bot Auth key."),
        save: bool = typer.Option(True, "--save/--no-save", help="Store the replay in the database."),
    ) -> None:
        """Replay a shopping task against the store and report whether the blocker hypothesis reproduces."""
        from .runner import replay_blocker

        _utf8()
        cfg = ReplayConfig.load()
        con = db.connect() if save else None
        try:
            res = replay_blocker(con, blocker, cfg, base_url=base_url, task=task, mode=mode, pause_s=pause,
                                 sign=True if sign else None, vision=True if vision else None)  # fmt: skip
        except HostNotAllowed as exc:
            typer.echo(f"refused: {exc}", err=True)
            raise typer.Exit(2) from exc
        finally:
            if con is not None:
                con.close()
        typer.echo(f"replay {res.replay_id}  mode={res.mode}  planner={res.planner}  blocker={blocker or '-'}")
        for s in res.steps:
            typer.echo(f"  {s.n:>2}. {s.action:<16} {s.status if s.status is not None else '-':>4}  {s.note[:90]}")
        typer.echo(f"task completed: {res.task_completed}" + (f" (order {res.order_id})" if res.order_id else ""))
        for w in res.workarounds:
            typer.echo(f"  workaround: {w}")
        for n in res.notes:
            typer.echo(f"  note: {n}")
        typer.echo(f"verdict: {res.verdict.upper()}  {res.explanation}")
        typer.echo(f"evidence: {res.evidence_dir}")

    @app.command("replay-all")
    def replay_all(
        top: int = typer.Option(None, "--top", help="Number of top blockers (default: replay.yaml top_n_blockers)."),
        base_url: str = typer.Option(None, "--base-url", help="Store to replay against."),
        mode: str = typer.Option(None, help="fetch or browser (default: each blocker's best mode)."),
        pause: float = typer.Option(None, help="Seconds between requests."),
    ) -> None:
        """Run one replay per top blocker (ranked by revenue at risk) and store the verdicts."""
        from .runner import run_replays

        _utf8()
        con = db.connect()
        try:
            counts = run_replays(
                con, top_n=top, base_url=base_url, mode=mode, pause_s=pause,
                on_step=lambda name, status, msg: typer.echo(f"{name:<8} {status:<9} {msg or ''}"),
            )  # fmt: skip
        except HostNotAllowed as exc:
            typer.echo(f"refused: {exc}", err=True)
            raise typer.Exit(2) from exc
        finally:
            con.close()
        typer.echo(", ".join(f"{k}={v}" for k, v in counts.items()))
        if counts["failed"]:
            raise typer.Exit(1)
