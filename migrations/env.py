"""Alembic environment.

Migrations run through a synchronous psycopg 3 connection even though the
application uses the async engine: Alembic's own API is synchronous, and the
async wrapper adds a layer of indirection to a process whose entire job is DDL.
The same `postgresql+psycopg://` URL serves both.

`target_metadata` is None because M0 has no ORM models, so `--autogenerate` is
unavailable and migrations are hand-written. M1 introduces models with the
first repository and can wire metadata in then.

Offline mode (`alembic upgrade --sql`) is not supported; nothing in the build
generates SQL scripts instead of applying them.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _database_url() -> str:
    url = os.environ.get("SMOKEJUMPER__DATABASE__URL")
    if not url:
        raise RuntimeError("SMOKEJUMPER__DATABASE__URL must be set to run migrations")
    return url


def run_migrations() -> None:
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


run_migrations()
