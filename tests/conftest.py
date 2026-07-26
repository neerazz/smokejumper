"""Shared fixtures.

Kept small on purpose: shared test infrastructure is where over-engineering
usually enters a codebase first, because every helper added here is one more
thing a reader must understand before they can trust a single test.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """The repository root, for tests that inspect committed files."""
    return REPO_ROOT


@pytest.fixture(scope="session")
def src_root(repo_root: Path) -> Path:
    """The importable source tree."""
    return repo_root / "src" / "smokejumper"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip service-backed tests unless the stack is actually reachable.

    A test that silently passes because its dependency was absent is worse than
    no test. Marked tests skip loudly instead, and CI sets SMOKEJUMPER_TEST_STACK=1
    to turn a skip into a hard requirement.
    """
    if os.environ.get("SMOKEJUMPER_TEST_STACK") == "1":
        return

    skip_integration = pytest.mark.skip(
        reason="needs Postgres/Redis; run `docker compose up -d` or set SMOKEJUMPER_TEST_STACK=1"
    )
    skip_e2e = pytest.mark.skip(
        reason="needs the full stack and a compose profile; set SMOKEJUMPER_TEST_STACK=1"
    )

    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
        if "e2e" in item.keywords:
            item.add_marker(skip_e2e)
