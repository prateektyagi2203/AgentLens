"""`agentlens synth ...` commands: offline, live and the before/after scenario."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from agentlens import settings

from .config import FRICTION_IDS
from .offline import BASE_DATE, OfflineResult, data_dir_for, run_offline

synth_app = typer.Typer(help="Synthetic traffic with ground truth (PRD 17).", no_args_is_help=True)
scenario_app = typer.Typer(help="Scripted scenarios.", no_args_is_help=True)
synth_app.add_typer(scenario_app, name="scenario")


def _parse_toggles(value: str | None) -> set[str] | None:
    if value is None:
        return None
    ids = {x.strip().upper() for x in value.split(",") if x.strip()}
    bad = ids - set(FRICTION_IDS)
    if bad:
        raise typer.BadParameter(f"unknown toggles: {sorted(bad)}")
    return ids


def _report(res: OfflineResult) -> None:
    rate = res.lines / res.seconds if res.seconds else 0
    typer.echo(
        f"run {res.run_id}: {res.sessions} sessions, {res.lines} log lines, {res.orders} orders "
        f"in {res.seconds:.1f}s ({rate:,.0f} lines/s)"
    )
    typer.echo(f"logs: {res.files[0].parent if res.files else '-'}  ({len(res.files)} files)")
    typer.echo(f"ground truth: {res.ground_truth}")


@synth_app.command("offline")
def offline(
    sessions: int = typer.Option(3000, help="Number of sessions."),
    days: float = typer.Option(7, help="Spread sessions over this many days."),
    seed: int = typer.Option(1, help="RNG seed (same seed, same output)."),
    out: Path = typer.Option(None, help="Output log directory (default: <data>/logs)."),
    start_date: str = typer.Option(BASE_DATE, help="First day (UTC, YYYY-MM-DD)."),
    state: str = typer.Option("before", help="Friction state: before | after (PRD Appendix C)."),
    toggles: str = typer.Option(None, help="Explicit active toggles, e.g. F05,F06 (overrides --state)."),
    run_id: str = typer.Option(None, help="Run id used in the ground-truth file name."),
    force: bool = typer.Option(False, help="Overwrite existing log files."),
) -> None:
    """Write synthetic native-schema JSONL logs without a store."""
    res = run_offline(sessions=sessions, days=days, seed=seed, out=out or settings.logs_dir(), start_date=start_date,
                      state=state, toggles=_parse_toggles(toggles), run_id=run_id, force=force)  # fmt: skip
    _report(res)


@synth_app.command("live")
def live(
    sessions: int = typer.Option(200, help="Number of sessions."),
    rate: str = typer.Option("20/s", help="Session arrival rate."),
    seed: int = typer.Option(1),
    store_url: str = typer.Option(None, help="Store base URL (default from config/synth.yaml)."),
    speed: float = typer.Option(10.0, help="Think-time speed-up factor."),
    browser_share: float = typer.Option(0.0, help="Share of browsing-agent sessions driven through Playwright."),
    run_id: str = typer.Option(None),
) -> None:
    """Drive the running store over HTTP (and Playwright for a sample of browsing agents)."""
    from .live import run_live

    res = asyncio.run(run_live(sessions=sessions, rate=rate, seed=seed, store_url=store_url, speed=speed,
                               browser_share=browser_share, data_dir=settings.data_dir(), run_id=run_id))  # fmt: skip
    typer.echo(f"live {res.run_id}: {res.sessions} sessions ({res.browser_sessions} via browser), {res.requests} requests "
               f"in {res.seconds:.1f}s, {res.errors} network errors")
    typer.echo(f"ground truth: {res.ground_truth}")
    typer.echo("Make sure the store runs with AGENTLENS_SYNTH_MODE=1 so it records X-Synth-Session.")


@scenario_app.command("before-after")
def before_after(
    before_days: float = typer.Option(7, help="Days in the Before state."),
    after_days: float = typer.Option(7, help="Days in the After state."),
    sessions: int = typer.Option(6000, help="Total sessions over both periods."),
    seed: int = typer.Option(1),
    out: Path = typer.Option(None, help="Output log directory (default: <data>/logs)."),
    start_date: str = typer.Option(BASE_DATE),
    run_id: str = typer.Option(None),
    force: bool = typer.Option(False),
) -> None:
    """Before state for N days, then the After state (PRD Appendix C) with a config_change line at the switch."""
    target = out or settings.logs_dir()
    res = run_offline(sessions=sessions, days=before_days + after_days, seed=seed, out=target, start_date=start_date,
                      run_id=run_id, force=force, switch_after_days=before_days)  # fmt: skip
    _report(res)
    typer.echo(f"toggles flipped Before -> After after {before_days:g} days (data dir {data_dir_for(target)})")
