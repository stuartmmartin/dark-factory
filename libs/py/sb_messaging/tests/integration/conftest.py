"""Platform tables plus a tenant-scoped `effects` table (RLS) in a schema of their own.

The Postgres container is shared by the whole pytest session, so this suite keeps its tables
in `sb_messaging_it` and never touches the `public` tables other suites create.
"""

from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path

import pytest
from confluent_kafka import Consumer, TopicPartition
from confluent_kafka.admin import AdminClient
from confluent_kafka.cimpl import NewTopic
from pytest_asyncio import is_async_test
from sqlalchemy import Column, MetaData, Table, Uuid, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from sb_db.engine import create_engine, session_factory
from sb_db.platform import PlatformTables, install_platform_tables
from sb_db.rls import enable_rls_sql, platform_table_ddl
from sb_messaging.publisher import KafkaPublisher

SCHEMA = "sb_messaging_it"
metadata = MetaData(schema=SCHEMA)
effects = Table(
    "effects",
    metadata,
    Column("event_id", Uuid, primary_key=True),
    Column("tenant_id", Uuid, nullable=False),
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
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        await conn.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        await conn.run_sync(metadata.create_all)
        for statement in [*enable_rls_sql(f"{SCHEMA}.effects"), *platform_table_ddl(SCHEMA)]:
            await conn.execute(text(statement))
        await conn.execute(text(f"GRANT USAGE ON SCHEMA {SCHEMA} TO sb_app"))
        await conn.execute(
            text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {SCHEMA} TO sb_app")
        )
        await conn.execute(text(f"GRANT USAGE ON ALL SEQUENCES IN SCHEMA {SCHEMA} TO sb_app"))
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


@pytest.fixture(autouse=True)
async def _empty_messaging_tables(admin_engine: AsyncEngine) -> None:
    """Every test starts with no outbox/inbox/effects rows, so relay counts are its own."""
    async with admin_engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {SCHEMA}.outbox, {SCHEMA}.inbox, {SCHEMA}.effects"))


@pytest.fixture
def platform() -> PlatformTables:
    return tables


@pytest.fixture
def effects_table() -> Table:
    return effects


@pytest.fixture
def admin_sessions(admin_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Superuser sessions: they see every tenant's rows (assertions only)."""
    return session_factory(admin_engine)


@pytest.fixture
def app_sessions(app_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """sb_app sessions: NOBYPASSRLS, like production."""
    return session_factory(app_engine)


@pytest.fixture
def create_topic(kafka_bootstrap: str) -> Callable[[str], None]:
    """Create a single-partition topic (one partition: the tests rely on total order)."""

    def create(topic: str) -> None:
        admin = AdminClient({"bootstrap.servers": kafka_bootstrap})
        futures = admin.create_topics(
            [NewTopic(topic, num_partitions=1, replication_factor=1)], operation_timeout=10
        )
        futures[topic].result(timeout=30)

    return create


@pytest.fixture
def publisher(kafka_bootstrap: str) -> Iterator[KafkaPublisher]:
    kafka = KafkaPublisher(kafka_bootstrap, "sb-messaging-it")
    yield kafka
    kafka.close()


def _committed_offset(bootstrap: str, group: str, topic: str) -> int:
    """The group's committed offset on partition 0 (OFFSET_INVALID if it never committed)."""
    reader = Consumer({"bootstrap.servers": bootstrap, "group.id": group})
    try:
        [partition] = reader.committed([TopicPartition(topic, 0)], timeout=10)
        return partition.offset
    finally:
        reader.close()


@pytest.fixture
def group_offset(kafka_bootstrap: str) -> Callable[[str, str], int]:
    return lambda group, topic: _committed_offset(kafka_bootstrap, group, topic)
