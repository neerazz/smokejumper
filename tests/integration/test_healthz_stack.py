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


def test_healthz_reports_every_component_an_incident_needs() -> None:
    """Postgres, Redis, and the worker — all three, or the check is a half-truth.

    Asserted as a contract rather than an exact body: a frozen dict fails whenever
    a new observable is added, which trains people to update the expectation
    instead of reading it. What must hold is that the three liveness fields are
    `ok` and that the operational counters are present.
    """
    port = os.environ.get("APP_HOST_PORT", "8000")
    response = httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=15.0)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["postgres"] == "ok"
    assert body["redis"] == "ok"
    assert body["worker"] == "ok", "a dead worker must never report healthy"
    assert body["recorder_write_failures"] == 0
    assert isinstance(body["queue_backlog"], int)


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
    # The worker survives unreachable dependencies by design: it retries rather
    # than exiting, so an outage that recovers does not need a container restart.
    assert body["worker"] in {"ok", "starting"}
