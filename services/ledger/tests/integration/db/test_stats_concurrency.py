"""SQL only: concurrent `increment()`s of one tenant never lose an update (atomic upsert).

The fake is single-threaded, so this property only means something against Postgres.
"""

import asyncio
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ledger.infrastructure.models import platform
from ledger.infrastructure.uow import SqlLedgerUnitOfWork
from sb_kernel.context import RequestContext, use_context
from sb_testing.clock import FakeClock

N = 10


async def test_concurrent_increments_serialize_on_the_row(
    ledger_sessions: async_sessionmaker[AsyncSession], fake_clock: FakeClock
) -> None:
    async def increment() -> int:
        async with SqlLedgerUnitOfWork(ledger_sessions, platform, fake_clock) as uow:
            accounts = await uow.stats.increment()
            await uow.commit()
            return accounts

    with use_context(RequestContext(tenant_id=uuid4(), actor="race", request_id="req-race")):
        returned = await asyncio.gather(*(increment() for _ in range(N)))
        async with SqlLedgerUnitOfWork(ledger_sessions, platform, fake_clock) as uow:
            assert await uow.stats.count() == N
    assert sorted(returned) == list(range(1, N + 1))
