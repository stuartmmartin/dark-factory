"""The journal tables defend themselves in Postgres, not only in the use case (migration 0002).

Raw SQL as sb_app (NOBYPASSRLS): a line can never reference another tenant's account, even when
the code forgets to check, because the composite foreign key includes `tenant_id` (foreign-key
checks bypass RLS). Entries are append-only: sb_app has no UPDATE or DELETE grant, and the
trigger stops even the owning migrator role.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import pool, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine as _create

from ledger.application.dto import OpenAccountCommand
from ledger.application.ports import UowFactory
from ledger.application.use_cases.open_account import OpenAccount
from ledger.infrastructure.models import platform
from ledger.infrastructure.uow import SqlLedgerUnitOfWork
from sb_db.engine import COMMAND_TIMEOUT_SECONDS, CONNECT_TIMEOUT_SECONDS
from sb_db.rls import TENANT_SETTING
from sb_kernel.clock import FixedClock
from sb_kernel.context import RequestContext, use_context

CLOCK = FixedClock(datetime(2026, 3, 1, 12, tzinfo=UTC))
INSERT_ENTRY = text(
    "INSERT INTO journal_entries (id, tenant_id, description, currency, posted_at) "
    "VALUES (:id, :tenant, 'Transfer', 'USD', now())"
)
INSERT_LINE = text(
    "INSERT INTO journal_lines (entry_id, line_no, tenant_id, account_id, side, amount) "
    "VALUES (:entry, :line_no, :tenant, :account, 'debit', 10)"
)


@pytest.fixture
def uow(ledger_sessions: async_sessionmaker[AsyncSession]) -> UowFactory:
    return lambda: SqlLedgerUnitOfWork(ledger_sessions, platform, CLOCK)


async def _open_account(uow: UowFactory, tenant: UUID) -> UUID:
    ctx = RequestContext(tenant_id=tenant, actor="journal-test", request_id="req-journal")
    with use_context(ctx):
        return (await OpenAccount(uow, CLOCK)(OpenAccountCommand(name="Cash", currency="USD"))).id


async def _connect(url: str) -> AsyncIterator[AsyncConnection]:
    engine = _create(
        url,
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
async def app_conn(ledger_db: str) -> AsyncIterator[AsyncConnection]:
    async for conn in _connect(ledger_db):
        yield conn


@pytest.fixture
async def migrator_conn(ledger_migrator_url: str) -> AsyncIterator[AsyncConnection]:
    async for conn in _connect(ledger_migrator_url):
        yield conn


async def _as_tenant(conn: AsyncConnection, tenant: UUID) -> None:
    await conn.execute(
        text("SELECT set_config(:k, :v, true)"), {"k": TENANT_SETTING, "v": str(tenant)}
    )


async def _execute_as(conn: AsyncConnection, tenant: UUID, statement: str) -> None:
    async with conn.begin():
        await _as_tenant(conn, tenant)
        await conn.execute(text(statement))


async def _post(conn: AsyncConnection, tenant: UUID, account: UUID) -> UUID:
    entry = uuid4()
    async with conn.begin():
        await _as_tenant(conn, tenant)
        await conn.execute(INSERT_ENTRY, {"id": entry, "tenant": tenant})
        await conn.execute(
            INSERT_LINE, {"entry": entry, "line_no": 1, "tenant": tenant, "account": account}
        )
    return entry


async def test_a_line_on_the_tenants_own_account_is_accepted(
    uow: UowFactory, app_conn: AsyncConnection
) -> None:
    tenant = uuid4()
    await _post(app_conn, tenant, await _open_account(uow, tenant))


async def test_a_line_on_another_tenants_account_is_rejected_by_the_foreign_key(
    uow: UowFactory, app_conn: AsyncConnection
) -> None:
    others_account = await _open_account(uow, uuid4())
    with pytest.raises(DBAPIError, match="fk_journal_lines_account_id_accounts"):
        await _post(app_conn, uuid4(), others_account)


@pytest.mark.parametrize(
    "statement",
    ["UPDATE journal_lines SET amount = 1", "DELETE FROM journal_lines"],
    ids=["update", "delete"],
)
async def test_sb_app_cannot_change_or_remove_a_posted_line(
    uow: UowFactory, app_conn: AsyncConnection, statement: str
) -> None:
    tenant = uuid4()
    await _post(app_conn, tenant, await _open_account(uow, tenant))
    with pytest.raises(DBAPIError, match="permission denied"):
        await _execute_as(app_conn, tenant, statement)


@pytest.mark.parametrize("table", ["journal_entries", "journal_lines"])
async def test_even_the_owner_cannot_update_a_journal_row(
    uow: UowFactory, app_conn: AsyncConnection, migrator_conn: AsyncConnection, table: str
) -> None:
    tenant = uuid4()
    await _post(app_conn, tenant, await _open_account(uow, tenant))
    with pytest.raises(DBAPIError, match="append-only"):
        async with migrator_conn.begin():
            await migrator_conn.execute(
                text(f"UPDATE {table} SET tenant_id = tenant_id WHERE tenant_id = :t"),  # noqa: S608
                {"t": tenant},
            )
