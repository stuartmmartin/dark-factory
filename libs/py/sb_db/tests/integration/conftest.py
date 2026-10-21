"""A throwaway schema: one tenant-scoped business table plus the platform tables, with RLS."""

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest
from pytest_asyncio import is_async_test
from sqlalchemy import Column, MetaData, String, Table, Uuid, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from sb_db.engine import create_engine, session_factory
from sb_db.platform import PlatformTables, install_platform_tables
from sb_db.rls import enable_rls_sql, platform_table_ddl

metadata = MetaData()
widgets = Table(
    "widgets",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("tenant_id", Uuid, nullable=False),
    Column("name", String, nullable=False),
)
tables = install_platform_tables(metadata)

_HERE = Path(__file__).parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Run this directory's async tests on the session loop: the pooled asyncpg connections
    of the session-scoped engines belong to it."""
    session_loop = pytest.mark.asyncio(loop_scope="session")
    for item in items:
        if is_async_test(item) and _HERE in item.path.parents:
            item.add_marker(session_loop, append=False)


@pytest.fixture(scope="session")
async def admin_engine(postgres_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(postgres_url)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.drop_all)
        await conn.run_sync(metadata.create_all)
        for statement in [*enable_rls_sql("widgets"), *platform_table_ddl()]:
            await conn.execute(text(statement))
        await conn.execute(
            text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO sb_app")
        )
        await conn.execute(text("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO sb_app"))
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
async def app_engine(
    admin_engine: AsyncEngine, postgres_app_url: str
) -> AsyncIterator[AsyncEngine]:
    del admin_engine  # schema must exist first
    engine = create_engine(postgres_app_url)
    yield engine
    await engine.dispose()


@pytest.fixture
def platform() -> PlatformTables:
    return tables


@pytest.fixture
def app_sessions(app_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return session_factory(app_engine)


@pytest.fixture
def widgets_table() -> Table:
    return widgets


@pytest.fixture
def tenant_a() -> UUID:
    return UUID(int=0xA)


@pytest.fixture
def tenant_b() -> UUID:
    return UUID(int=0xB)
