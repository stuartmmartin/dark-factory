"""Shared Alembic env for every service: `run_migrations(url, target_metadata)` in env.py."""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import MetaData, pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from sb_db.engine import CONNECT_TIMEOUT_SECONDS

# DDL (index builds, backfills) can legitimately outlast the runtime 30 s command timeout.
MIGRATION_COMMAND_TIMEOUT_SECONDS = 600


def _do_run(connection: Connection, target_metadata: MetaData) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_online(url: str, target_metadata: MetaData) -> None:
    engine = create_async_engine(
        url,
        poolclass=pool.NullPool,
        connect_args={
            "timeout": CONNECT_TIMEOUT_SECONDS,
            "command_timeout": MIGRATION_COMMAND_TIMEOUT_SECONDS,
        },
    )
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_do_run, target_metadata)
    finally:
        await engine.dispose()


def run_migrations(url: str, target_metadata: MetaData) -> None:
    if context.is_offline_mode():
        context.configure(
            url=url, target_metadata=target_metadata, literal_binds=True, compare_type=True
        )
        with context.begin_transaction():
            context.run_migrations()
        return
    asyncio.run(_run_online(url, target_metadata))
