"""Two tenants on one ledger database (Review Focus #2): RLS keeps each to its own rows.

Through the use cases, another tenant's account reads as NotFound (never Forbidden) and its count
as 0. Through raw SQL as sb_app the same holds, and with no tenant set nothing is visible (what
the admin sees, D9). The migrator role bypasses RLS, which is why the admin must never use it.
"""

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import pool, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine as _create

from ledger.application.dto import (
    GetAccountQuery,
    OpenAccountCommand,
    RecordAccountOpenedCommand,
    SnapshotAccountCountCommand,
)
from ledger.application.ports import UowFactory
from ledger.application.use_cases.get_account import GetAccount
from ledger.application.use_cases.open_account import OpenAccount
from ledger.application.use_cases.record_account_opened import RecordAccountOpened
from ledger.application.use_cases.snapshot_account_count import SnapshotAccountCount
from ledger.infrastructure.models import platform
from ledger.infrastructure.uow import SqlLedgerUnitOfWork
from sb_db.engine import COMMAND_TIMEOUT_SECONDS, CONNECT_TIMEOUT_SECONDS
from sb_db.rls import TENANT_SETTING
from sb_kernel.clock import FixedClock
from sb_kernel.context import RequestContext, use_context
from sb_kernel.errors import NotFound

CLOCK = FixedClock(datetime(2026, 3, 1, 12, tzinfo=UTC))
TENANT_TABLES = (
    "accounts",
    "account_counts",
    "account_count_snapshots",
    "idempotency_keys",
    "audit_events",
)
COUNT_SQL = {table: text(f"SELECT count(*) FROM {table}") for table in TENANT_TABLES}  # noqa: S608
NOTHING = dict.fromkeys(TENANT_TABLES, 0)
# What tenant A's fixture writes: one account, its count, one snapshot, the snapshot's
# idempotency key, and three audit events (open, increment, snapshot).
TENANT_A_ROWS = {**dict.fromkeys(TENANT_TABLES, 1), "audit_events": 3}


def _ctx(tenant: UUID) -> RequestContext:
    return RequestContext(tenant_id=tenant, actor="rls-test", request_id="req-rls")


@pytest.fixture
def uow(ledger_sessions: async_sessionmaker[AsyncSession]) -> UowFactory:
    return lambda: SqlLedgerUnitOfWork(ledger_sessions, platform, CLOCK)


@pytest.fixture
async def tenant_a_account(uow: UowFactory) -> tuple[UUID, UUID]:
    """(tenant A, A's account id): opened, counted and snapshotted under an idempotency key."""
    tenant = uuid4()
    with use_context(_ctx(tenant)):
        opened = await OpenAccount(uow, CLOCK)(OpenAccountCommand(name="A's cash", currency="USD"))
        await RecordAccountOpened(uow)(RecordAccountOpenedCommand(account_id=opened.id))
        await SnapshotAccountCount(uow)(
            SnapshotAccountCountCommand(as_of=date(2026, 3, 1), idempotency_key="snapshot-a")
        )
    return tenant, opened.id


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


async def _counts(conn: AsyncConnection, tenant: UUID | None) -> dict[str, int]:
    """Row counts in one transaction, scoped to `tenant` (or no tenant at all)."""
    async with conn.begin():
        if tenant is not None:
            await conn.execute(
                text("SELECT set_config(:k, :v, true)"), {"k": TENANT_SETTING, "v": str(tenant)}
            )
        return {name: (await conn.execute(sql)).scalar_one() for name, sql in COUNT_SQL.items()}


async def test_another_tenant_reads_the_account_as_not_found_and_counts_zero(
    uow: UowFactory, tenant_a_account: tuple[UUID, UUID]
) -> None:
    _, account_id = tenant_a_account
    with use_context(_ctx(uuid4())):
        with pytest.raises(NotFound):
            await GetAccount(uow)(GetAccountQuery(account_id=account_id))
        async with uow() as b:
            assert await b.stats.count() == 0


async def test_the_owning_tenant_sees_its_account_and_count(
    uow: UowFactory, tenant_a_account: tuple[UUID, UUID]
) -> None:
    tenant, account_id = tenant_a_account
    with use_context(_ctx(tenant)):
        assert (await GetAccount(uow)(GetAccountQuery(account_id=account_id))).id == account_id
        async with uow() as a:
            assert await a.stats.count() == 1


async def test_raw_sql_as_sb_app_sees_nothing_of_another_tenant_or_without_a_tenant(
    tenant_a_account: tuple[UUID, UUID], app_conn: AsyncConnection
) -> None:
    tenant, _ = tenant_a_account
    assert await _counts(app_conn, uuid4()) == NOTHING
    assert await _counts(app_conn, None) == NOTHING  # what the admin sees (D9)
    assert await _counts(app_conn, tenant) == TENANT_A_ROWS


async def test_the_migrator_bypasses_rls_so_the_admin_must_never_use_it(
    tenant_a_account: tuple[UUID, UUID], migrator_conn: AsyncConnection
) -> None:
    tenant, account_id = tenant_a_account
    async with migrator_conn.begin():
        owner = (
            await migrator_conn.execute(
                text("SELECT tenant_id FROM accounts WHERE id = :id"), {"id": account_id}
            )
        ).scalar_one()
    assert owner == tenant


async def _insert_as(conn: AsyncConnection, session_tenant: UUID, row_tenant: UUID) -> None:
    async with conn.begin():
        await conn.execute(
            text("SELECT set_config(:k, :v, true)"),
            {"k": TENANT_SETTING, "v": str(session_tenant)},
        )
        await conn.execute(
            text(
                "INSERT INTO accounts (id, tenant_id, name, currency, opened_at) "
                "VALUES (:id, :tenant, 'forged', 'USD', now())"
            ),
            {"id": uuid4(), "tenant": row_tenant},
        )


async def test_inserting_a_row_for_another_tenant_is_rejected_by_with_check(
    tenant_a_account: tuple[UUID, UUID], app_conn: AsyncConnection
) -> None:
    tenant_a, _ = tenant_a_account
    with pytest.raises(DBAPIError, match="row-level security"):
        await _insert_as(app_conn, session_tenant=uuid4(), row_tenant=tenant_a)
