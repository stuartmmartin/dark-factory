"""The joined consumer path on Postgres (Review Focus #3, D13), without Kafka.

`RecordAccountOpened` runs inside `inbox.process`'s transaction through `joined(uow)`. A handler
that fails after the use case ran commits nothing (no count, no audit row, no inbox row); the
redelivery applies exactly once; a further duplicate is skipped by the inbox.
"""

from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ledger.application.dto import OpenAccountCommand
from ledger.application.use_cases.open_account import OpenAccount
from ledger.domain.events import AccountOpened
from ledger.infrastructure.models import platform
from ledger.infrastructure.uow import SqlLedgerUnitOfWork
from ledger.interface.consumers.account_opened import CONSUMER, handle
from sb_kernel.context import RequestContext, use_context
from sb_messaging.envelope import EventEnvelope
from sb_messaging.inbox import process
from sb_testing.clock import FakeClock

type Sessions = async_sessionmaker[AsyncSession]
type Handler = Callable[[EventEnvelope, SqlLedgerUnitOfWork], Awaitable[None]]
type AuditCount = Callable[[UUID, UUID], Awaitable[int]]
type InboxHas = Callable[[str, UUID], Awaitable[bool]]


async def _failing_after_handle(envelope: EventEnvelope, uow: SqlLedgerUnitOfWork) -> None:
    await handle(envelope, uow)
    raise RuntimeError("boom")


async def _count(sessions: Sessions, clock: FakeClock, tenant: UUID) -> int:
    with use_context(RequestContext(tenant_id=tenant, actor="tester", request_id="req-1")):
        async with SqlLedgerUnitOfWork(sessions, platform, clock) as uow:
            return await uow.stats.count()


async def test_a_failed_handler_commits_nothing_and_the_redelivery_applies_once(
    ledger_sessions: Sessions,
    fake_clock: FakeClock,
    increment_audits: AuditCount,
    inbox_has: InboxHas,
) -> None:
    tenant = uuid4()

    def uow_factory() -> SqlLedgerUnitOfWork:
        return SqlLedgerUnitOfWork(ledger_sessions, platform, fake_clock)

    with use_context(RequestContext(tenant_id=tenant, actor="tester", request_id="req-1")):
        opened = await OpenAccount(uow_factory, fake_clock)(
            OpenAccountCommand(name="Cash", currency="USD")
        )
    account_id = opened.id
    envelope = EventEnvelope(
        event_id=uuid4(),
        event_type=AccountOpened.event_type,
        schema_version=AccountOpened.schema_version,
        topic=AccountOpened.topic(),
        key=str(account_id),
        occurred_at=fake_clock.now(),
        tenant_id=tenant,
        actor="tester",
        request_id="req-1",
        trace_id=None,
        payload=AccountOpened(account_id=account_id, currency="USD").model_dump(mode="json"),
    )

    async def deliver(handler: Handler = handle) -> bool:
        return await process(
            envelope,
            consumer=CONSUMER,
            handler=handler,
            uow_factory=uow_factory,
            tables=platform,
            clock=fake_clock,
        )

    # 1. The handler fails after RecordAccountOpened ran: nothing persists, inbox row included.
    with pytest.raises(RuntimeError, match="boom"):
        await deliver(_failing_after_handle)
    assert await _count(ledger_sessions, fake_clock, tenant) == 0
    assert await increment_audits(tenant, account_id) == 0
    assert not await inbox_has(CONSUMER, envelope.event_id)

    # 2. The redelivery applies once, with its audit row and inbox row.
    assert await deliver() is True
    assert await _count(ledger_sessions, fake_clock, tenant) == 1
    assert await increment_audits(tenant, account_id) == 1
    assert await inbox_has(CONSUMER, envelope.event_id)

    # 3. A further duplicate is skipped by the inbox.
    assert await deliver() is False
    assert await _count(ledger_sessions, fake_clock, tenant) == 1
    assert await increment_audits(tenant, account_id) == 1
