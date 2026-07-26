"""The Smokejumper HTTP application. M0 exposes `GET /healthz` and nothing else.

`/healthz` is wired to the container healthcheck and to `docker compose up
--wait`, so it probes Postgres and Redis for real. An endpoint that returned
200 because the process had started would make every dependent wait succeed
against a system that cannot serve an incident.

Webhook routes arrive with the Receiver in M1 (SPEC 5.1).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from smokejumper.persistence.database import check_connection, create_engine

# A dependency that has not answered in three seconds is down as far as an
# orchestrator is concerned; without a bound, a black-holed socket would hang
# the healthcheck until Docker's own timeout kills it and reports nothing useful.
_PROBE_TIMEOUT_SECONDS = 3.0


async def _probe(check: Awaitable[Any]) -> str:
    """Await `check`, reporting `ok` or the failure class name."""
    try:
        async with asyncio.timeout(_PROBE_TIMEOUT_SECONDS):
            await check
    except Exception as error:
        return f"down: {type(error).__name__}"
    return "ok"


def create_app(*, database_url: str, redis_url: str) -> FastAPI:
    """Build the application against explicit dependency URLs.

    URLs are injected rather than read from a settings object so that a test can
    point the app at an unreachable dependency and assert the failure path.
    """
    engine = create_engine(database_url)
    redis = Redis.from_url(redis_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await engine.dispose()
            await redis.aclose()

    app = FastAPI(title="Smokejumper", version="0.1.0", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        checks = {
            "postgres": await _probe(check_connection(engine)),
            "redis": await _probe(redis.ping()),
        }
        healthy = all(state == "ok" for state in checks.values())
        return JSONResponse(
            status_code=200 if healthy else 503,
            content={"status": "ok" if healthy else "unhealthy", **checks},
        )

    return app


def app_from_env() -> FastAPI:
    """Composition root for `uvicorn --factory smokejumper.app:app_from_env`.

    This is the only place in the application that reads the process
    environment. It resolves the two URLs SPEC 11.3 names and fails immediately
    if either is absent, because a missing database URL must surface at boot
    rather than at minute nine of an incident (SPEC 2d).

    The layered settings object (SPEC 2d, M0.2) replaces the two lookups below
    once it exists; `create_app` keeps its signature either way.
    """
    return create_app(
        database_url=_required_env("SMOKEJUMPER__DATABASE__URL"),
        redis_url=_required_env("SMOKEJUMPER__REDIS__URL"),
    )


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be set")
    return value
