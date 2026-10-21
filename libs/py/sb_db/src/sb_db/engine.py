"""Async engine and session factory with bounded connect/command timeouts (C6).

Bound parameters are hidden from SQLAlchemy log lines and exception messages (C9).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

CONNECT_TIMEOUT_SECONDS = 10
COMMAND_TIMEOUT_SECONDS = 30


def create_engine(url: str, *, pool_size: int = 5, echo: bool = False) -> AsyncEngine:
    return create_async_engine(
        url,
        pool_size=pool_size,
        echo=echo,
        pool_pre_ping=True,
        hide_parameters=True,  # bound values (PII, money) never reach logs or error messages
        connect_args={
            "timeout": CONNECT_TIMEOUT_SECONDS,
            "command_timeout": COMMAND_TIMEOUT_SECONDS,
        },
    )


def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
