"""What `alembic upgrade head` actually produced in the running stack.

Postgres is not host-published, so these assertions run `psql` inside the
container. The table set is asserted exactly, not by membership: the point is to
catch a table that was created before the milestone that writes it.
"""

from __future__ import annotations

import re
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


def test_schema_holds_exactly_the_tables_with_writers(repo_root: Path) -> None:
    """Asserted as an exact set, not by membership.

    The point is to catch a table created before the code that writes it. Each
    name below has a writer today: `events` from the Receiver, `runs`, `tickets`,
    and the retry-idempotency `ticket_actions` ledger from the worker. `approvals`
    (M5) and `episodes` (M3) are
    deliberately absent, and adding either early should fail here.
    """
    tables = _query(
        repo_root,
        "SELECT table_name FROM information_schema.tables"
        " WHERE table_schema = 'public' ORDER BY table_name",
    )

    assert tables.splitlines() == [
        "alembic_version",
        "events",
        "runs",
        "ticket_actions",
        "tickets",
    ]


def _expected_head(repo_root: Path) -> str:
    """The head revision the committed migrations define.

    Derived rather than hardcoded. A literal made this test fail on every new
    migration for the wrong reason — the assertion that matters is "the database
    is at the revision this checkout defines", which catches migrations that did
    not run. Hardcoding turned that into an unrelated edit each time, and a test
    people routinely edit to make it pass is a test they stop reading.

    Head is the one revision no other revision points back to.
    """
    versions = repo_root / "migrations" / "versions"
    revisions: dict[str, str | None] = {}
    for path in versions.glob("[0-9]*.py"):
        text = path.read_text(encoding="utf-8")
        revision = re.search(r'^revision:\s*str\s*=\s*"([^"]+)"', text, re.M)
        down = re.search(r'^down_revision:.*=\s*(?:"([^"]+)"|None)', text, re.M)
        assert revision, f"{path.name} declares no revision"
        revisions[revision.group(1)] = down.group(1) if down and down.group(1) else None

    assert revisions, "no migrations found"
    parents = {down for down in revisions.values() if down}
    heads = sorted(set(revisions) - parents)
    assert len(heads) == 1, f"expected exactly one head, found {heads}"
    return heads[0]


def test_head_revision_is_applied(repo_root: Path) -> None:
    """The running database is at the revision this checkout defines."""
    assert _query(repo_root, "SELECT version_num FROM alembic_version") == _expected_head(repo_root)


def test_vector_extension_is_installed(repo_root: Path) -> None:
    assert (
        _query(repo_root, "SELECT extname FROM pg_extension WHERE extname = 'vector'") == "vector"
    )
