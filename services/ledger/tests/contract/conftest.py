"""The port contract suite: every test runs against the in-memory fakes AND the SQL adapters.

`uow_factory` is parametrized over `"fake"` and `"sql"`; the same assertions must hold for both,
so the fakes the unit tests trust cannot drift from Postgres (T3). Each test runs under a fresh
random tenant. The `"sql"` half needs Docker (marked integration); `ledger_sessions` is resolved
only there, so the `"fake"` half runs without it.
"""

from collections.abc import Callable, Iterator
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from ledger_fakes import (  # type: ignore[import-not-found]
    FakeLedgerUoW,
    LedgerState,
    fake_factory,
    fake_joined,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ledger.application.ports import LedgerUnitOfWork, UowFactory
from ledger.domain.accounts import Account
from ledger.infrastructure.models import platform
from ledger.infrastructure.uow import SqlLedgerUnitOfWork
from sb_db.uow import joined
from sb_kernel.context import RequestContext, current_context, use_context
from sb_kernel.money import Currency
from sb_testing.clock import FakeClock

OPENED_AT = datetime(2026, 3, 1, 12, tzinfo=UTC)


def _context() -> RequestContext:
    return RequestContext(tenant_id=uuid4(), actor="contract", request_id="req-contract")


@pytest.fixture(params=["fake", pytest.param("sql", marks=pytest.mark.integration)])
def uow_factory(request: pytest.FixtureRequest, fake_clock: FakeClock) -> Iterator[UowFactory]:
    if request.param == "sql":
        sessions: async_sessionmaker[AsyncSession] = request.getfixturevalue("ledger_sessions")
        factory: UowFactory = lambda: SqlLedgerUnitOfWork(sessions, platform, fake_clock)  # noqa: E731
    else:
        factory = fake_factory(LedgerState())
    with use_context(_context()):
        yield factory


@pytest.fixture
def other_tenant() -> Callable[[], AbstractContextManager[RequestContext]]:
    """`with other_tenant():` runs the block as a second, fresh tenant."""
    return lambda: use_context(_context())


@pytest.fixture
def new_account() -> Callable[[], Account]:
    """A new account of the current tenant."""
    return lambda: Account(
        id=uuid4(),
        tenant_id=current_context().tenant_id,
        name="Operating cash",
        currency=Currency.of("USD"),
        opened_at=OPENED_AT,
    )


def _join(uow: LedgerUnitOfWork) -> Callable[[], AbstractAsyncContextManager[LedgerUnitOfWork]]:
    if isinstance(uow, SqlLedgerUnitOfWork):
        return joined(uow)
    assert isinstance(uow, FakeLedgerUoW)
    return fake_joined(uow)


@pytest.fixture
def join() -> Callable[
    [LedgerUnitOfWork], Callable[[], AbstractAsyncContextManager[LedgerUnitOfWork]]
]:
    """`sb_db.uow.joined` for the SQL unit of work, `fake_joined` for the fake."""
    return _join
