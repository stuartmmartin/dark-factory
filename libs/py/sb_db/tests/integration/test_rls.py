from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Table, func, insert, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from sb_db.rls import enable_rls_sql

type Sessions = async_sessionmaker[AsyncSession]


async def _with_tenant[T](
    sessions: Sessions, tenant: UUID, fn: Callable[[AsyncSession], Awaitable[T]]
) -> T:
    async with sessions() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)}
        )
        return await fn(session)


async def test_tenant_cannot_see_other_tenants_rows(
    app_sessions: Sessions, widgets_table: Table, tenant_a: UUID, tenant_b: UUID
) -> None:
    for tenant in (tenant_a, tenant_b):

        async def _add(session: AsyncSession, tenant: UUID = tenant) -> None:
            await session.execute(
                insert(widgets_table).values(id=uuid4(), tenant_id=tenant, name="w")
            )

        await _with_tenant(app_sessions, tenant, _add)

    async def tenants_visible(session: AsyncSession) -> set[UUID]:
        rows = await session.execute(select(widgets_table.c.tenant_id).distinct())
        return {r[0] for r in rows}

    assert await _with_tenant(app_sessions, tenant_a, tenants_visible) == {tenant_a}


async def test_writing_another_tenants_row_is_rejected(
    app_sessions: Sessions, widgets_table: Table, tenant_a: UUID, tenant_b: UUID
) -> None:
    async def write_b(session: AsyncSession) -> None:
        await session.execute(
            insert(widgets_table).values(id=uuid4(), tenant_id=tenant_b, name="x")
        )

    with pytest.raises(DBAPIError, match="row-level security"):
        await _with_tenant(app_sessions, tenant_a, write_b)


async def test_no_tenant_set_sees_nothing(
    app_sessions: Sessions, widgets_table: Table, tenant_a: UUID
) -> None:
    async def _add(session: AsyncSession) -> None:
        await session.execute(
            insert(widgets_table).values(id=uuid4(), tenant_id=tenant_a, name="w")
        )

    await _with_tenant(app_sessions, tenant_a, _add)  # a row exists, just not for "no tenant"
    async with app_sessions() as session:
        count = (
            await session.execute(select(func.count()).select_from(widgets_table))
        ).scalar_one()
    assert count == 0


async def test_force_binds_the_table_owner_too(admin_engine: AsyncEngine) -> None:
    async with admin_engine.connect() as conn:
        transaction = await conn.begin()
        try:
            await conn.execute(text("CREATE ROLE rls_owner_probe NOLOGIN NOSUPERUSER NOBYPASSRLS"))
            await conn.execute(text("GRANT CREATE, USAGE ON SCHEMA public TO rls_owner_probe"))
            await conn.execute(text("SET LOCAL ROLE rls_owner_probe"))
            await conn.execute(text("CREATE TABLE owned (tenant_id uuid NOT NULL)"))
            for statement in enable_rls_sql("owned"):
                await conn.execute(text(statement))
            await conn.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(UUID(int=1))}
            )
            await conn.execute(text("INSERT INTO owned VALUES (:t)"), {"t": UUID(int=1)})
            await conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": ""})
            visible = (await conn.execute(text("SELECT count(*) FROM owned"))).scalar_one()
        finally:
            await transaction.rollback()
    assert visible == 0
