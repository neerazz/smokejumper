"""`/healthz` against the running default stack.

Both tests are marked `integration`. The second one only needs unreachable
addresses, but it asserts the same endpoint's failure branch, so it is kept
beside the success case rather than split across suites.
"""

from __future__ import annotations

import os

import httpx
import pytest

from smokejumper.app import create_app

pytestmark = pytest.mark.integration

# Nothing is listening on port 1, so the probes fail fast and deterministically.
_UNREACHABLE_DATABASE = "postgresql+psycopg://smokejumper:smokejumper@127.0.0.1:1/smokejumper"
_UNREACHABLE_REDIS = "redis://127.0.0.1:1/0"


def test_healthz_reports_both_dependencies_up() -> None:
    port = os.environ.get("APP_HOST_PORT", "8000")
    response = httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=15.0)

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "postgres": "ok", "redis": "ok"}


async def test_healthz_fails_closed_when_dependencies_are_unreachable() -> None:
    app = create_app(database_url=_UNREACHABLE_DATABASE, redis_url=_UNREACHABLE_REDIS)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://app.invalid") as client:
        response = await client.get("/healthz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unhealthy"
    assert body["postgres"].startswith("down: ")
    assert body["redis"].startswith("down: ")
