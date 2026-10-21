import asyncio
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from sb_db.platform import PlatformTables
from sb_db.uow import SqlAlchemyUnitOfWork
from sb_kernel.clock import Clock
from sb_kernel.context import RequestContext, use_context
from sb_kernel.errors import Conflict, IdempotencyKeyReused


async def test_save_then_get_round_trips_per_tenant(
    app_sessions: async_sessionmaker[AsyncSession],
    platform: PlatformTables,
    fake_clock: Clock,
    tenant_a: UUID,
    tenant_b: UUID,
) -> None:
    with use_context(RequestContext(tenant_id=tenant_a, actor="t", request_id="r")):
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as uow:
            await uow.idempotency.save("k1", "hash-1", {"id": "x"})
            await uow.commit()
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as uow:
            stored = await uow.idempotency.get("k1")
    assert stored is not None
    assert (stored.request_hash, dict(stored.response)) == ("hash-1", {"id": "x"})
    with use_context(RequestContext(tenant_id=tenant_b, actor="t", request_id="r")):
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as uow:
            assert await uow.idempotency.get("k1") is None


async def test_reusing_a_key_for_a_different_request_is_rejected_as_reused(
    app_sessions: async_sessionmaker[AsyncSession],
    platform: PlatformTables,
    fake_clock: Clock,
    tenant_a: UUID,
) -> None:
    with use_context(RequestContext(tenant_id=tenant_a, actor="t", request_id="r")):
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as first:
            await first.idempotency.save("k-dup", "hash-1", {"id": "x"})
            await first.commit()
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as second:
            with pytest.raises(IdempotencyKeyReused, match="different request"):
                await second.idempotency.save("k-dup", "hash-2", {"id": "y"})


async def test_saving_the_same_request_again_is_a_conflict(
    app_sessions: async_sessionmaker[AsyncSession],
    platform: PlatformTables,
    fake_clock: Clock,
    tenant_a: UUID,
) -> None:
    with use_context(RequestContext(tenant_id=tenant_a, actor="t", request_id="r")):
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as first:
            await first.idempotency.save("k-same", "hash-1", {"id": "x"})
            await first.commit()
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as second:
            with pytest.raises(Conflict, match="idempotency key already in use") as caught:
                await second.idempotency.save("k-same", "hash-1", {"id": "x"})
    assert not isinstance(caught.value, IdempotencyKeyReused)


async def _until_a_backend_waits_on_a_lock(engine: AsyncEngine) -> None:
    """Poll until some backend is blocked on a lock (pg_stat_activity is snapshotted per
    transaction, so each probe is its own transaction)."""
    query = text("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock'")
    async with asyncio.timeout(10):
        while True:
            async with engine.connect() as conn:
                if (await conn.execute(query)).scalar_one():
                    return
            await asyncio.sleep(0.01)


async def test_a_concurrent_duplicate_save_is_a_conflict_and_only_one_commits(
    admin_engine: AsyncEngine,
    app_sessions: async_sessionmaker[AsyncSession],
    platform: PlatformTables,
    fake_clock: Clock,
    tenant_a: UUID,
) -> None:
    first_saved = asyncio.Event()

    async def first() -> None:
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as uow:
            await uow.idempotency.save("k-race", "hash-1", {"id": "first"})
            first_saved.set()
            await _until_a_backend_waits_on_a_lock(admin_engine)  # second is blocked on us
            await uow.commit()

    async def second() -> None:
        await first_saved.wait()
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as uow:
            await uow.idempotency.save("k-race", "hash-1", {"id": "second"})
            await uow.commit()

    with use_context(RequestContext(tenant_id=tenant_a, actor="t", request_id="r")):
        results = await asyncio.gather(first(), second(), return_exceptions=True)
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as uow:
            stored = await uow.idempotency.get("k-race")
    assert results[0] is None
    assert type(results[1]) is Conflict
    assert stored is not None
    assert dict(stored.response) == {"id": "first"}
