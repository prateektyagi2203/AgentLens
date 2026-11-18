"""`agentlens` command line entrypoint. Subcommands are registered by each milestone."""

from __future__ import annotations

import typer

from . import __version__, db, settings

app = typer.Typer(help="AgentLens: agent analytics for ecommerce.", no_args_is_help=True)


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


if __name__ == "__main__":
    app()
