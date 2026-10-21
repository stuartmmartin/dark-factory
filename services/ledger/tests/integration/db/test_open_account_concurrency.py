"""SQL only: two concurrent `OpenAccount`s with one idempotency key open one account (R3).

Both units of work read the key before either commits (a barrier holds them there), so neither
sees a stored response: the second one's `idempotency.save` waits on the first one's
uncommitted key row and then raises `Conflict`, rolling back its account, audit and outbox rows.
The fake is single-threaded, so this race only means something against Postgres.
"""

import asyncio
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ledger.application.dto import AccountResult, OpenAccountCommand
from ledger.application.use_cases.open_account import OpenAccount
from ledger.infrastructure.models import platform
from ledger.infrastructure.uow import SqlLedgerUnitOfWork
from sb_kernel.context import RequestContext, use_context
from sb_kernel.errors import Conflict
from sb_kernel.uow import StoredResponse
from sb_testing.clock import FakeClock

KEY = "open-race-1"


async def test_two_concurrent_opens_with_one_key_give_one_account_and_one_conflict(
    ledger_sessions: async_sessionmaker[AsyncSession], fake_clock: FakeClock
) -> None:
    both_read_the_key = asyncio.Barrier(2)

    class ReadThenWait(SqlLedgerUnitOfWork):
        """The real SQL unit of work, held after its idempotency read until both have read."""

        async def __aenter__(self) -> "ReadThenWait":
            await super().__aenter__()
            store = self.idempotency
            read = store.get

            async def first_get(key: str) -> StoredResponse | None:
                # Only OpenAccount's own read waits: `save` re-reads the key on a conflict.
                store.get = read  # type: ignore[method-assign]
                stored = await read(key)
                await both_read_the_key.wait()
                return stored

            store.get = first_get  # type: ignore[method-assign]
            return self

    open_account = OpenAccount(
        lambda: ReadThenWait(ledger_sessions, platform, fake_clock), fake_clock
    )
    command = OpenAccountCommand(name="Race", currency="USD", idempotency_key=KEY)
    tenant = uuid4()
    with use_context(RequestContext(tenant_id=tenant, actor="race", request_id="req-race")):
        outcomes = await asyncio.wait_for(
            asyncio.gather(open_account(command), open_account(command), return_exceptions=True),
            timeout=30,
        )

    successes = [o for o in outcomes if isinstance(o, AccountResult)]
    conflicts = [o for o in outcomes if isinstance(o, Conflict)]
    assert (len(successes), len(conflicts)) == (1, 1), outcomes
    assert not successes[0].replayed
    assert await _accounts_of(ledger_sessions, fake_clock, tenant) == [successes[0].id]


async def _accounts_of(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, tenant: UUID
) -> list[UUID]:
    with use_context(RequestContext(tenant_id=tenant, actor="check", request_id="req-check")):
        async with SqlLedgerUnitOfWork(sessions, platform, clock) as uow:
            rows = await uow.session.execute(text("SELECT id FROM accounts"))
            return [row.id for row in rows]
