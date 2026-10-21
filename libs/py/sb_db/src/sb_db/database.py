"""Create a service database on first migrate (compose never needs editing per service)."""

from __future__ import annotations

import re

from sqlalchemy import pool, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from sb_db.engine import COMMAND_TIMEOUT_SECONDS, CONNECT_TIMEOUT_SECONDS

_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_DUPLICATE_DATABASE = "42P04"


def _async_url(url: str) -> str:
    """Accept plain `postgresql://` URLs too; this module always talks through asyncpg."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url.removeprefix(prefix)
    return url


async def ensure_database(admin_url: str, name: str, owner: str) -> bool:
    """Create database `name` owned by `owner` unless it exists; True if it was created."""
    if not _IDENT.fullmatch(name) or not _IDENT.fullmatch(owner):
        raise ValueError("database and owner names must be simple lowercase identifiers")
    # CREATE DATABASE cannot run inside a transaction block, hence AUTOCOMMIT.
    engine = create_async_engine(
        _async_url(admin_url),
        poolclass=pool.NullPool,
        isolation_level="AUTOCOMMIT",
        connect_args={
            "timeout": CONNECT_TIMEOUT_SECONDS,
            "command_timeout": COMMAND_TIMEOUT_SECONDS,
        },
    )
    try:
        async with engine.connect() as conn:
            exists = (
                await conn.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
                )
            ).scalar_one_or_none()
            if exists is not None:
                return False
            # DDL takes no bind parameters; both names are validated identifiers above.
            try:
                await conn.execute(text(f'CREATE DATABASE "{name}" OWNER "{owner}"'))
            except DBAPIError as exc:  # lost a race with a concurrent migrate: it exists now
                if getattr(exc.orig, "sqlstate", None) == _DUPLICATE_DATABASE:
                    return False
                raise
            return True
    finally:
        await engine.dispose()
