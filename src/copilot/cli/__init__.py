"""Temporal SRE Copilot CLI."""

import typer

from copilot.cli.db import app as db_app
from copilot.cli.kb import app as kb_app

app = typer.Typer(
    name="copilot",
    help="Temporal SRE Copilot - AI-powered observability agent",
    no_args_is_help=True,
)

app.add_typer(db_app, name="db", help="Database operations")
app.add_typer(kb_app, name="kb", help="Knowledge base operations")


@app.callback()
def main() -> None:
    """Temporal SRE Copilot CLI."""
    pass


if __name__ == "__main__":
    app()
