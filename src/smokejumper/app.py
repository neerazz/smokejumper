"""The Smokejumper HTTP application. M0 exposes `GET /healthz` and nothing else.

`/healthz` is wired to the container healthcheck and to `docker compose up
--wait`, so it probes Postgres and Redis for real. An endpoint that returned
200 because the process had started would make every dependent wait succeed
against a system that cannot serve an incident.

Webhook routes arrive with the Receiver in M1 (SPEC 5.1).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text

from smokejumper.persistence.database import check_connection, create_engine
from smokejumper.receiver.routes import build_router
from smokejumper.recorder.writer import Recorder
from smokejumper.worker import WorkerHandle, queue_depth, worker_task

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


def create_app(
    *,
    database_url: str,
    redis_url: str,
    datadog_secret: str = "",
) -> FastAPI:
    """Build the application against explicit dependency URLs.

    URLs are injected rather than read from a settings object so that a test can
    point the app at an unreachable dependency and assert the failure path.

    `datadog_secret` defaults to empty, and an empty secret makes every Datadog
    delivery fail verification (SPEC 5.1). That is the intended default: a
    deployment that forgot to configure the secret must reject alerts loudly
    rather than accept unauthenticated ones.
    """
    engine = create_engine(database_url)
    redis = Redis.from_url(redis_url)
    recorder = Recorder(Path(os.environ.get("SMOKEJUMPER_LOG_DIR", "logs")))

    # Populated at startup so `/healthz` can report worker liveness. A module
    # attribute rather than a closure variable because the health route needs to
    # read whatever the current lifespan set, including `None` before startup.
    state: dict[str, Any] = {"worker": None}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # The worker runs beside the API so `docker compose up` yields a system
        # that actually processes an alert, rather than one that only accepts it.
        async with worker_task(engine, redis, recorder) as handle:
            state["worker"] = handle
            try:
                yield
            finally:
                await engine.dispose()
                await redis.aclose()

    app = FastAPI(title="Smokejumper", version="0.1.0", lifespan=lifespan)
    app.include_router(build_router(engine=engine, redis=redis, datadog_secret=datadog_secret))

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        """Liveness of everything an incident depends on, not just the process.

        The worker is checked because it is the component whose death is
        invisible: the API keeps accepting alerts and the queue keeps growing
        while nothing investigates. Reporting only Postgres and Redis would leave
        the container "healthy" through exactly that failure.
        """
        worker: WorkerHandle | None = state["worker"]
        checks = {
            "postgres": await _probe(check_connection(engine)),
            "redis": await _probe(redis.ping()),
            "worker": worker.status() if worker else "starting",
        }
        healthy = all(value == "ok" for value in checks.values())

        # Reported, not gated on: a recorder write failure is serious (SPEC 5.8
        # makes JSONL the source of truth) but it does not mean the process
        # cannot serve, and flapping the container on it would lose more.
        details: dict[str, Any] = {"recorder_write_failures": recorder.failures}
        with contextlib.suppress(Exception):
            details["queue"] = await queue_depth(redis)

        return JSONResponse(
            status_code=200 if healthy else 503,
            content={"status": "ok" if healthy else "unhealthy", **checks, **details},
        )

    @app.get("/runs/{fingerprint}")
    async def run_for(fingerprint: str) -> JSONResponse:
        """What the system concluded about one incident, and the ticket it filed.

        The operator-facing read path. Without it the only way to see an outcome
        is to open psql, which makes the system unusable by the person it is for.
        """
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        """
                        SELECT r.run_id, r.status, r.conclusion, r.finished_at,
                               r.audit_log_file, r.audit_start_offset, r.audit_end_offset,
                               t.external_id, t.update_count
                          FROM runs r
                          LEFT JOIN tickets t ON t.fingerprint = r.fingerprint
                         WHERE r.fingerprint = :fingerprint
                      ORDER BY r.started_at DESC
                         LIMIT 1
                        """
                    ),
                    {"fingerprint": fingerprint},
                )
            ).first()

        if row is None:
            return JSONResponse(status_code=404, content={"status": "no run for fingerprint"})

        conclusion = row.conclusion or {}
        return JSONResponse(
            content={
                "run_id": str(row.run_id),
                "status": row.status,
                "conclusion_status": conclusion.get("status"),
                "confidence": conclusion.get("confidence"),
                "summary_md": conclusion.get("summary_md"),
                "findings": conclusion.get("findings", []),
                "proposed_actions": conclusion.get("proposed_actions", []),
                "ticket": row.external_id,
                "ticket_updates": row.update_count,
                "audit": {
                    "file": row.audit_log_file,
                    "start_offset": row.audit_start_offset,
                    "end_offset": row.audit_end_offset,
                },
            }
        )

    return app


def app_from_env() -> FastAPI:
    """Composition root for `uvicorn --factory smokejumper.app:app_from_env`.

    Configuration is assembled and validated by `smokejumper.config`, which is
    the single reader of the process environment (SPEC 2d). Every layered source
    and every fail-closed gate therefore applies to a container boot, which
    reading two variables directly here would have bypassed.

    Imported inside the function so that `create_app` stays usable by a test
    that never touches configuration.
    """
    from smokejumper.config import load_settings

    settings = load_settings()
    secret = settings.webhooks.datadog.secret
    return create_app(
        database_url=str(settings.database.url),
        redis_url=str(settings.redis.url),
        datadog_secret="" if secret is None else secret.get_secret_value(),
    )
