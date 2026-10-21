from datetime import UTC, datetime
from typing import cast

import pytest
from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sb_db.platform import install_platform_tables
from sb_db.uow import SqlAlchemyUnitOfWork
from sb_kernel.clock import FixedClock
from sb_kernel.errors import Forbidden


def _no_db() -> AsyncSession:
    raise AssertionError("the unit of work touched the database without a request context")


async def test_uow_without_context_raises_before_db() -> None:
    sessions = cast(async_sessionmaker[AsyncSession], _no_db)
    uow = SqlAlchemyUnitOfWork(
        sessions, install_platform_tables(MetaData()), FixedClock(datetime(2026, 1, 1, tzinfo=UTC))
    )
    with pytest.raises(Forbidden, match="no request context"):
        async with uow:
            pass
