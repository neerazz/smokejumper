"""What `alembic upgrade head` actually produced in the running stack.

Postgres is not host-published, so these assertions run `psql` inside the
container. The table set is asserted exactly, not by membership: the point is to
catch a table that was created before the milestone that writes it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _query(repo_root: Path, sql: str) -> str:
    docker = shutil.which("docker")
    if docker is None:
        pytest.fail("docker must be on PATH to inspect the running stack")

    completed = subprocess.run(
        [
            docker,
            "compose",
            "exec",
            "-T",
            "postgres",
            "psql",
            "--username=smokejumper",
            "--dbname=smokejumper",
            "--no-align",
            "--tuples-only",
            "--command",
            sql,
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def test_schema_holds_exactly_the_m0_tables(repo_root: Path) -> None:
    tables = _query(
        repo_root,
        "SELECT table_name FROM information_schema.tables"
        " WHERE table_schema = 'public' ORDER BY table_name",
    )

    assert tables.splitlines() == ["alembic_version", "events", "runs"]


def test_head_revision_is_applied(repo_root: Path) -> None:
    assert _query(repo_root, "SELECT version_num FROM alembic_version") == "0001_core_tables"


def test_vector_extension_is_installed(repo_root: Path) -> None:
    assert (
        _query(repo_root, "SELECT extname FROM pg_extension WHERE extname = 'vector'") == "vector"
    )
