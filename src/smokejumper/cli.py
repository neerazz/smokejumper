"""The `smokejumper` command line.

Only the one command M0 can honestly answer is implemented. Every other
subcommand named in SPEC 12 (`logs`, `replay`, `eval`, `fixtures replay`) lands
with the milestone that gives it behavior: a subcommand that exists and exits 0
without doing anything is worse than a missing one, because a reader trusts it.

There is deliberately no `doctor ports` here. The host-port preflight is
`scripts/check_host_ports.py`, which SPEC 11.2 names as the single inventory
holder. A second implementation inside the package would be strictly worse at
the job: a preflight has to run *before* `uv sync` and *before* the stack starts,
and this module can do neither, because installing the package is what makes it
importable and the app process is what holds port 8000.
"""

from __future__ import annotations

import typer

app = typer.Typer(help="Smokejumper — an agentic SRE.", no_args_is_help=True)


@app.callback()
def main() -> None:
    """Group anchor. Required, and not decoration.

    Typer collapses a single-command app into a bare command, which would make
    `smokejumper check-config` fail with "unexpected extra argument" while
    `smokejumper` alone silently ran it. This callback keeps the subcommand
    spelling stable as later milestones add `logs`, `replay`, and `eval`, so the
    commands SPEC 12 promises do not change shape as the CLI grows.
    """


@app.command("check-config")
def check_config() -> None:
    """Assemble and validate configuration, then exit non-zero if it is unusable.

    The settings object is owned by `smokejumper.config` (SPEC 2d) and imported
    lazily so that `--help` works without touching configuration. Both pydantic's
    own validation failure and `ConfigError` are `ValueError`s, so one guard
    covers them and an operator running a preflight check reads the problem
    rather than a traceback.
    """
    from smokejumper.config import load_settings

    try:
        settings = load_settings()
    except ValueError as error:
        typer.echo(f"configuration invalid: {error}", err=True)
        raise typer.Exit(1) from error
    typer.echo(f"configuration valid for SMOKEJUMPER_ENV={settings.env}")
