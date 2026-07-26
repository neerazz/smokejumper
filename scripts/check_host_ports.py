#!/usr/bin/env python3
"""Fail before startup when a host port Smokejumper publishes is already taken.

Imports only the standard library so it runs on a bare CPython before `uv sync`
and before `docker compose up` — a preflight that needed the project installed
would run too late to be worth having.

SPEC.md §11.2 is the contract. `tests/scripts/test_check_host_ports.py` parses
that table and fails if it disagrees with `INVENTORY` below, so the table and
this script cannot drift apart.
"""

from __future__ import annotations

import argparse
import shutil
import socket
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass

LOOPBACK = "127.0.0.1"

# Distance from a taken port to the one suggested in its place. Large enough that
# the replacement is not itself a well-known service port.
OVERRIDE_OFFSET = 10_000


@dataclass(frozen=True)
class PublishedPort:
    """One host-published port: the whole reason this script exists."""

    profile: str
    service: str
    container_port: int
    host_port: int
    env_var: str


# Every host-published port in v1, and nothing else. Services absent from this
# tuple are reachable by service name on the Compose network, so they cannot
# collide with anything on the host.
INVENTORY = (
    PublishedPort("default", "app", 8000, 8000, "APP_HOST_PORT"),
    PublishedPort("lab", "prometheus", 9090, 9090, "PROMETHEUS_HOST_PORT"),
    PublishedPort("obs", "phoenix", 6006, 6006, "PHOENIX_HOST_PORT"),
)

# `fixtures` starts only the replayer, which has no listener. It is selectable
# but contributes no ports, so it cannot be derived from INVENTORY.
SELECTABLE_PROFILES = ("lab", "fixtures", "obs")

# Services started with no `--profile` flag. Always checked.
CORE_PROFILE = "default"


def parse_profiles(raw: str) -> tuple[str, ...]:
    """Split a `--profiles` value, rejecting names Compose does not define."""
    names = tuple(name.strip() for name in raw.split(",") if name.strip())
    unknown = [name for name in names if name not in SELECTABLE_PROFILES]
    if unknown:
        known = ", ".join(SELECTABLE_PROFILES)
        raise ValueError(f"unknown profile(s): {', '.join(unknown)}; choose from {known}")
    return names


def selected_ports(profiles: Iterable[str]) -> tuple[PublishedPort, ...]:
    """Ports published by the core services plus the requested profiles."""
    wanted = {CORE_PROFILE, *profiles}
    return tuple(port for port in INVENTORY if port.profile in wanted)


def find_collisions(
    ports: Iterable[PublishedPort],
    is_free: Callable[[int], bool],
) -> tuple[PublishedPort, ...]:
    """Ports that cannot be bound right now, in inventory order."""
    return tuple(port for port in ports if not is_free(port.host_port))


def override_hint(port: PublishedPort) -> str:
    """The exact `.env` assignment that moves a port out of the way."""
    return f"{port.env_var}={port.host_port + OVERRIDE_OFFSET}"


def probe_loopback(port: int) -> bool:
    """True when `127.0.0.1:port` can be bound right now.

    Binding is the only honest test. A connect probe cannot tell a listener from
    a wildcard bind that will still refuse ours, and `*:8080` on this workstation
    is exactly that case. SO_REUSEADDR is deliberately not set: it would only
    mask the conflict this script is looking for.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((LOOPBACK, port))
        except OSError:
            return False
    return True


def describe_holder(port: int) -> str | None:
    """Best-effort `command (pid N)` for whoever holds the port.

    Advisory only, and never load-bearing: lsof is absent on some hosts and an
    unprivileged caller cannot see another user's sockets. A collision is
    reported either way. The argv is fixed and the only interpolated value is an
    int from our own inventory, so nothing untrusted reaches the shell.
    """
    lsof = shutil.which("lsof")
    if lsof is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603
            [lsof, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-F", "cp"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    command: str | None = None
    pid: str | None = None
    for line in result.stdout.splitlines():
        if line.startswith("p"):
            pid = line[1:]
        elif line.startswith("c"):
            command = line[1:]
        if command and pid:
            return f"{command} (pid {pid})"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Smokejumper host ports (SPEC.md §11.2).")
    parser.add_argument(
        "--profiles",
        default="",
        help=(
            "comma-separated compose profiles to include "
            f"({', '.join(SELECTABLE_PROFILES)}); core services are always checked"
        ),
    )
    args = parser.parse_args()

    try:
        profiles = parse_profiles(args.profiles)
    except ValueError as error:
        print(f"ERROR: {error}")
        return 2

    ports = selected_ports(profiles)
    collisions = find_collisions(ports, probe_loopback)

    for port in collisions:
        holder = describe_holder(port.host_port) or "an unidentified process"
        print(
            f"ERROR: host port {port.host_port} for service '{port.service}' "
            f"(profile {port.profile}) is held by {holder}"
        )
        print(f"       set {override_hint(port)} in .env, or any other free port")

    if collisions:
        print(f"host ports: FAIL ({len(collisions)} of {len(ports)} checked port(s) unavailable)")
        return 1
    print(f"host ports: PASS ({len(ports)} checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
