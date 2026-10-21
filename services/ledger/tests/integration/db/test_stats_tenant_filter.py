"""SQL only: the stats reads filter by the unit of work's tenant themselves (defence in depth).

RLS already scopes them for `sb_app`. Here they run on a BYPASSRLS session (`sb_migrator`), where
RLS does not apply, so only the explicit `WHERE tenant_id = <current>` keeps another tenant's
rows out. The fake has no RLS to bypass, so this is not a contract test.
"""

from collections.abc import AsyncIterator
from datetime import date
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ledger.infrastructure.repositories import SqlAccountStatsRepository
from sb_db.engine import create_engine, session_factory
from sb_testing.clock import FakeClock

AS_OF = date(2026, 3, 1)


@pytest.fixture
async def bypass_rls_session(
    ledger_db: str, ledger_migrator_url: str
) -> AsyncIterator[AsyncSession]:
    del ledger_db  # migrated first
    engine = create_engine(ledger_migrator_url)
    try:
        async with session_factory(engine)() as session:
            yield session
    finally:
        await engine.dispose()


async def _seed(session: AsyncSession, tenant: UUID, clock: FakeClock, times: int) -> None:
    stats = SqlAccountStatsRepository(session, tenant, clock)
    for _ in range(times):
        await stats.increment()
    await stats.upsert_snapshot(AS_OF, times)


async def test_count_and_snapshot_read_only_the_current_tenant_without_rls(
    bypass_rls_session: AsyncSession, fake_clock: FakeClock
) -> None:
    mine, other = uuid4(), uuid4()
    await _seed(bypass_rls_session, mine, fake_clock, 2)
    await _seed(bypass_rls_session, other, fake_clock, 5)

    stats = SqlAccountStatsRepository(bypass_rls_session, mine, fake_clock)
    assert await stats.count() == 2
    assert await stats.snapshot(AS_OF) == 2
    empty = SqlAccountStatsRepository(bypass_rls_session, uuid4(), fake_clock)
    assert await empty.count() == 0
    assert await empty.snapshot(AS_OF) is None
    await bypass_rls_session.rollback()  # leave no rows behind
