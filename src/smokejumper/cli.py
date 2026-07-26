"""The `smokejumper` command line.

Only the two commands M0 can honestly answer are implemented. Every other
subcommand named in SPEC 12 (`logs`, `replay`, `eval`, `distill`,
`bootstrap-secrets`) lands with the milestone that gives it behavior: a
subcommand that exists and exits 0 without doing anything is worse than a
missing one, because a reader trusts it.
"""

from __future__ import annotations

import os
import socket

import typer

app = typer.Typer(help="Smokejumper — an agentic SRE.", no_args_is_help=True)
doctor = typer.Typer(help="Preflight checks that must pass before the stack starts.")
app.add_typer(doctor, name="doctor")


@app.command("check-config")
def check_config() -> None:
    """Assemble and validate configuration, then exit non-zero if it is unusable.

    The settings object is owned by `smokejumper.config` (SPEC 2d) and imported
    lazily so that `--help` and `doctor` work without touching configuration.
    Pydantic reports invalid configuration as a `ValueError`; it is caught here
    because an operator running a preflight check should read the problem, not a
    traceback.
    """
    # The suppression is temporary: `smokejumper.config` is M0.2 and is being
    # written in parallel, so type checking cannot resolve it yet. Delete the
    # comment, not the import, once that module is merged.
    from smokejumper.config import load_settings  # pyright: ignore[reportMissingImports]

    try:
        settings = load_settings()
    except ValueError as error:
        typer.echo(f"configuration invalid: {error}", err=True)
        raise typer.Exit(1) from error
    typer.echo(f"configuration valid for SMOKEJUMPER_ENV={settings.env}")


@doctor.command("ports")
def doctor_ports() -> None:
    """Report whether the host ports the default stack publishes are free.

    The default stack publishes exactly one: the app, on loopback. Postgres and
    Redis are reachable only by service name on the Compose network, so they
    cannot collide with anything on this workstation. The `lab` and `obs`
    profiles publish their own ports and extend this check when they land.

    `APP_HOST_PORT` is read from the environment rather than from settings
    because it is a Compose interpolation variable, not an application value —
    the app itself always listens on 8000 inside the container (SPEC 11.2).
    """
    port = int(os.environ.get("APP_HOST_PORT", "8000"))
    if _is_bindable("127.0.0.1", port):
        typer.echo(f"app 127.0.0.1:{port} free")
        return
    typer.echo(
        f"app 127.0.0.1:{port} is already in use; set APP_HOST_PORT to a free port",
        err=True,
    )
    raise typer.Exit(1)


def _is_bindable(host: str, port: int) -> bool:
    """True when nothing else holds `host:port`.

    `SO_REUSEADDR` is deliberately not set: the question is whether a listener
    is present, and reuse would answer yes even when one is.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True
