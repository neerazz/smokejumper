"""Deployment-level architecture requirements that imports cannot enforce."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from smokejumper.persistence.database import SCHEMA_HEAD


def test_strict_langgraph_deserialization_is_set_before_import(repo_root: Path) -> None:
    """CVE-2026-28277 hardening must live in the process environment (SPEC 2)."""
    compose = yaml.safe_load((repo_root / "docker-compose.yml").read_text(encoding="utf-8"))
    app_environment = compose["services"]["app"]["environment"]
    dockerfile = (repo_root / "Dockerfile").read_text(encoding="utf-8")

    assert app_environment["LANGGRAPH_STRICT_MSGPACK"] == "true"
    assert "LANGGRAPH_STRICT_MSGPACK=true" in dockerfile


def test_ci_uses_an_isolated_disposable_compose_project(repo_root: Path) -> None:
    """CI teardown may delete volumes only under its run-specific project name."""
    workflow = (repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert (
        "COMPOSE_PROJECT_NAME: smokejumper-ci-${{ github.run_id }}-${{ github.run_attempt }}"
        in workflow
    )
    assert 'docker compose -p "$COMPOSE_PROJECT_NAME" up' in workflow
    assert 'docker compose -p "$COMPOSE_PROJECT_NAME" down -v' in workflow


def test_health_schema_revision_matches_the_migration_head(repo_root: Path) -> None:
    """A new migration cannot leave `/healthz` accepting the previous schema."""
    revisions: dict[str, str | None] = {}
    for path in (repo_root / "migrations" / "versions").glob("[0-9]*.py"):
        text = path.read_text(encoding="utf-8")
        revision = re.search(r'^revision:\s*str\s*=\s*"([^"]+)"', text, re.M)
        down = re.search(r'^down_revision:.*=\s*(?:"([^"]+)"|None)', text, re.M)
        assert revision
        revisions[revision.group(1)] = down.group(1) if down and down.group(1) else None

    parents = {parent for parent in revisions.values() if parent}
    (derived_head,) = set(revisions) - parents
    assert SCHEMA_HEAD == derived_head
