"""Raw reads for the messaging tests, as sb_app on the `ledger_test` database.

`audit_events` is under RLS, so it is read with the tenant set; `inbox` and `outbox` have no RLS.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from uuid import UUID

import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.ext.asyncio import create_async_engine as _create

from sb_db.engine import COMMAND_TIMEOUT_SECONDS, CONNECT_TIMEOUT_SECONDS
from sb_db.rls import TENANT_SETTING

# Test modules repeat these aliases: under --import-mode=importlib they cannot import conftest.
type AuditCount = Callable[[UUID, UUID], Awaitable[int]]
type InboxHas = Callable[[str, UUID], Awaitable[bool]]
type OutboxEventId = Callable[[UUID], Awaitable[UUID]]


@pytest.fixture
async def app_conn(ledger_db: str) -> AsyncIterator[AsyncConnection]:
    engine = _create(
        ledger_db,
        poolclass=pool.NullPool,
        connect_args={
            "timeout": CONNECT_TIMEOUT_SECONDS,
            "command_timeout": COMMAND_TIMEOUT_SECONDS,
        },
    )
    try:
        async with engine.connect() as conn:
            yield conn
    finally:
        await engine.dispose()


@pytest.fixture
def increment_audits(app_conn: AsyncConnection) -> AuditCount:
    """The tenant's `account_count.increment` audit rows for one account."""

    async def count(tenant: UUID, account_id: UUID) -> int:
        async with app_conn.begin():
            await app_conn.execute(
                text("SELECT set_config(:k, :v, true)"), {"k": TENANT_SETTING, "v": str(tenant)}
            )
            return (
                await app_conn.execute(
                    text(
                        "SELECT count(*) FROM audit_events "
                        "WHERE action = 'account_count.increment' AND entity_id = :id"
                    ),
                    {"id": str(account_id)},
                )
            ).scalar_one()

    return count


@pytest.fixture
def inbox_has(app_conn: AsyncConnection) -> InboxHas:
    async def has(consumer: str, event_id: UUID) -> bool:
        async with app_conn.begin():
            found = await app_conn.execute(
                text("SELECT 1 FROM inbox WHERE consumer = :c AND event_id = :e"),
                {"c": consumer, "e": event_id},
            )
            return found.first() is not None

    return has


@pytest.fixture
def outbox_event_id(app_conn: AsyncConnection) -> OutboxEventId:
    """The event id of the AccountOpened outbox row for one account (keyed by account id)."""

    async def event_id(account_id: UUID) -> UUID:
        async with app_conn.begin():
            return (
                await app_conn.execute(
                    text("SELECT event_id FROM outbox WHERE key = :k"), {"k": str(account_id)}
                )
            ).scalar_one()

    return event_id
