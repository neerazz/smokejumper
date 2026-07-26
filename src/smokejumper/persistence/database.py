"""Async engine and session factory over the one Postgres database (SPEC 2).

M0 owns connectivity and nothing else. There are no ORM models, repositories,
or unit-of-work helpers here: the schema is defined by the Alembic migrations
under `migrations/`, and M1 adds repositories when there is data to store.

Callers pass a URL rather than a settings object so persistence never depends
on how configuration is assembled (SPEC 2d).
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_engine(database_url: str) -> AsyncEngine:
    """Build the async engine for `database_url`.

    `pool_pre_ping` is on because Postgres outlives no restart gracefully from
    a pooled connection's point of view: without it, the first request after a
    database restart fails on a dead socket instead of reconnecting, which
    would make `/healthz` report an outage the database has already recovered
    from.
    """
    return create_async_engine(database_url, pool_pre_ping=True)


async def check_connection(engine: AsyncEngine) -> None:
    """Round-trip one query, raising whatever the driver raises on failure."""
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
