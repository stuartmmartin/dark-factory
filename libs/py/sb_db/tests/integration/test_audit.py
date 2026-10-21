from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import insert, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from sb_db.audit import verify_chain
from sb_db.platform import PlatformTables
from sb_db.uow import SqlAlchemyUnitOfWork
from sb_kernel.clock import Clock
from sb_kernel.context import RequestContext, use_context

type Sessions = async_sessionmaker[AsyncSession]


async def _record_three(
    sessions: Sessions, platform: PlatformTables, clock: Clock, tenant: UUID
) -> None:
    with use_context(RequestContext(tenant_id=tenant, actor="t", request_id="r")):
        for i in range(3):
            async with SqlAlchemyUnitOfWork(sessions, platform, clock) as uow:
                uow.audit.record(
                    action="thing.touch",
                    entity_type="thing",
                    entity_id=str(i),
                    before=None,
                    after={"i": i},
                )
                await uow.commit()


async def test_chain_verifies_and_rows_are_append_only(
    app_sessions: Sessions, platform: PlatformTables, fake_clock: Clock, tenant_b: UUID
) -> None:
    await _record_three(app_sessions, platform, fake_clock, tenant_b)
    with use_context(RequestContext(tenant_id=tenant_b, actor="t", request_id="r")):
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as uow:
            assert await verify_chain(uow.session, tenant_b, platform)
            with pytest.raises(DBAPIError, match="append-only"):
                await uow.session.execute(update(platform.audit_events).values(action="tampered"))


async def test_tampering_breaks_the_chain(
    admin_engine: AsyncEngine, app_sessions: Sessions, platform: PlatformTables, fake_clock: Clock
) -> None:
    tenant = UUID(int=0xC)  # own tenant: tampering never leaks into other tests' chains
    await _record_three(app_sessions, platform, fake_clock, tenant)
    async with admin_engine.begin() as conn:
        await conn.execute(text("ALTER TABLE audit_events DISABLE TRIGGER USER"))
        await conn.execute(
            text(
                "UPDATE audit_events SET action = 'tampered' WHERE seq = "
                "(SELECT min(seq) FROM audit_events WHERE tenant_id = :t)"
            ),
            {"t": tenant},
        )
        await conn.execute(text("ALTER TABLE audit_events ENABLE TRIGGER USER"))
    with use_context(RequestContext(tenant_id=tenant, actor="t", request_id="r")):
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as uow:
            assert not await verify_chain(uow.session, tenant, platform)


async def test_chain_verifies_with_decimal_and_nested_payloads(
    app_sessions: Sessions, platform: PlatformTables, fake_clock: Clock
) -> None:
    tenant = UUID(int=0xD)
    with use_context(RequestContext(tenant_id=tenant, actor="t", request_id="r", trace_id="tr")):
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as uow:
            uow.audit.record(
                action="money.move",
                entity_type="transfer",
                entity_id="t-1",
                before={"amount": Decimal("1.10"), "legs": [{"id": UUID(int=7)}]},
                after={"amount": Decimal("2.50"), "z": None, "a": True},
                reason="correction",
            )
            await uow.commit()
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as uow:
            assert await verify_chain(uow.session, tenant, platform)


async def test_truncate_is_blocked_even_for_the_owner(admin_engine: AsyncEngine) -> None:
    with pytest.raises(DBAPIError, match="append-only"):
        async with admin_engine.begin() as conn:
            await conn.execute(text("TRUNCATE audit_events"))


async def test_a_forked_chain_is_rejected(
    app_sessions: Sessions, platform: PlatformTables, fake_clock: Clock
) -> None:
    tenant = UUID(int=0xE)
    row = {
        "tenant_id": tenant,
        "actor": "t",
        "action": "a",
        "entity_type": "e",
        "entity_id": "1",
        "request_id": "r",
        "recorded_at": fake_clock.now(),
        "prev_hash": None,
    }
    async with app_sessions() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)}
        )
        await session.execute(insert(platform.audit_events).values(**row, hash="h1"))
        with pytest.raises(IntegrityError, match="uq_audit_events_tenant_prev_hash"):
            await session.execute(insert(platform.audit_events).values(**row, hash="h2"))


async def test_verify_chain_refuses_a_tenant_other_than_the_sessions(
    app_sessions: Sessions,
    platform: PlatformTables,
    fake_clock: Clock,
    tenant_a: UUID,
    tenant_b: UUID,
) -> None:
    with use_context(RequestContext(tenant_id=tenant_b, actor="t", request_id="r")):
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as uow:
            with pytest.raises(ValueError, match="tenant"):
                await verify_chain(uow.session, tenant_a, platform)
