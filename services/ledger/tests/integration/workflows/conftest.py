"""Shared setup for the workflow tests, on the migrated `ledger_test` database.

The activity reaches its use case through `activities.bind(container)`; here the container is a
minimal one holding a real `SnapshotAccountCount` on the session's sb_app engine
(`ledger_sessions`).
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from uuid import UUID

import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine as _create

from ledger.application.dto import OpenAccountCommand, RecordAccountOpenedCommand
from ledger.application.use_cases.open_account import OpenAccount
from ledger.application.use_cases.record_account_opened import RecordAccountOpened
from ledger.application.use_cases.snapshot_account_count import SnapshotAccountCount
from ledger.infrastructure.models import platform
from ledger.infrastructure.uow import SqlLedgerUnitOfWork
from ledger.interface.workflows import activities
from sb_db.engine import COMMAND_TIMEOUT_SECONDS, CONNECT_TIMEOUT_SECONDS
from sb_db.rls import TENANT_SETTING
from sb_kernel.context import RequestContext, use_context
from sb_testing.clock import FakeClock

# Test modules repeat these aliases: under --import-mode=importlib they cannot import conftest.
type Seed = Callable[[UUID, int], Awaitable[None]]
type SnapshotAudits = Callable[[UUID, date], Awaitable[int]]
type StoredSnapshot = Callable[[UUID, date], Awaitable[int | None]]


@dataclass(frozen=True)
class _SnapshotContainer:
    snapshot_account_count: SnapshotAccountCount


@pytest.fixture
def uow_factory(
    ledger_sessions: async_sessionmaker[AsyncSession], fake_clock: FakeClock
) -> Callable[[], SqlLedgerUnitOfWork]:
    def factory() -> SqlLedgerUnitOfWork:
        return SqlLedgerUnitOfWork(ledger_sessions, platform, fake_clock)

    return factory


@pytest.fixture
def bound_activity(uow_factory: Callable[[], SqlLedgerUnitOfWork]) -> None:
    """Bind the activity to a container on the test DB, as `ledger.worker` does."""
    activities.bind(_SnapshotContainer(SnapshotAccountCount(uow_factory)))


@pytest.fixture
def seed_accounts(uow_factory: Callable[[], SqlLedgerUnitOfWork], fake_clock: FakeClock) -> Seed:
    """Open `n` accounts for the tenant and count each, as the AccountOpened consumer would."""

    async def seed(tenant: UUID, n: int) -> None:
        with use_context(RequestContext(tenant_id=tenant, actor="tester", request_id="req-1")):
            for i in range(n):
                opened = await OpenAccount(uow_factory, fake_clock)(
                    OpenAccountCommand(name=f"Account {i}", currency="USD")
                )
                await RecordAccountOpened(uow_factory)(
                    RecordAccountOpenedCommand(account_id=opened.id)
                )

    return seed


@pytest.fixture
async def snapshot_audits(ledger_db: str) -> AsyncIterator[SnapshotAudits]:
    """The tenant's `account_count.snapshot` audit rows for one date (RLS: tenant set)."""
    engine = _create(
        ledger_db,
        poolclass=pool.NullPool,
        connect_args={
            "timeout": CONNECT_TIMEOUT_SECONDS,
            "command_timeout": COMMAND_TIMEOUT_SECONDS,
        },
    )

    async def count(tenant: UUID, as_of: date) -> int:
        async with engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config(:k, :v, true)"), {"k": TENANT_SETTING, "v": str(tenant)}
            )
            return (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM audit_events "
                        "WHERE action = 'account_count.snapshot' AND entity_id = :id"
                    ),
                    {"id": as_of.isoformat()},
                )
            ).scalar_one()

    try:
        yield count
    finally:
        await engine.dispose()


@pytest.fixture
def stored_snapshot(uow_factory: Callable[[], SqlLedgerUnitOfWork]) -> StoredSnapshot:
    async def read(tenant: UUID, as_of: date) -> int | None:
        with use_context(RequestContext(tenant_id=tenant, actor="tester", request_id="req-1")):
            async with uow_factory() as uow:
                return await uow.stats.snapshot(as_of)

    return read
