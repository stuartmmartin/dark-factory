"""End to end through real Kafka: OpenAccount → outbox → relay → topic → inbox consumer →
RecordAccountOpened. The tenant's count becomes 1 and the inbox records the event.

Rows other tests left in the outbox may be published and consumed too. The test's handler skips
any envelope from another tenant before `handle`, so it neither changes other tenants' counts nor
depends on their accounts still existing; assertions are about this test's tenant only.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ledger.application.dto import OpenAccountCommand
from ledger.application.use_cases.open_account import OpenAccount
from ledger.infrastructure.models import platform
from ledger.infrastructure.uow import SqlLedgerUnitOfWork
from ledger.interface.consumers.account_opened import CONSUMER, TOPIC, handle
from sb_kernel.context import RequestContext, use_context
from sb_messaging.consumer import KafkaInboxConsumer
from sb_messaging.envelope import EventEnvelope
from sb_messaging.publisher import KafkaPublisher
from sb_messaging.relay import OutboxRelay
from sb_testing.clock import FakeClock

HANDLED_TIMEOUT_SECONDS = 30
MAX_RELAY_RUNS = 50  # a backlog from other tests can exceed one batch

type Sessions = async_sessionmaker[AsyncSession]
type InboxHas = Callable[[str, UUID], Awaitable[bool]]
type OutboxEventId = Callable[[UUID], Awaitable[UUID]]


@pytest.fixture
async def publisher(kafka_bootstrap: str) -> AsyncIterator[KafkaPublisher]:
    kafka = KafkaPublisher(kafka_bootstrap, "test-relay")
    try:
        yield kafka
    finally:
        await asyncio.to_thread(kafka.close)


async def test_an_opened_account_is_counted_through_kafka(
    *,
    ledger_sessions: Sessions,
    fake_clock: FakeClock,
    kafka_bootstrap: str,
    publisher: KafkaPublisher,
    inbox_has: InboxHas,
    outbox_event_id: OutboxEventId,
) -> None:
    tenant = uuid4()
    ctx = RequestContext(tenant_id=tenant, actor="tester", request_id="req-1")

    def uow_factory() -> SqlLedgerUnitOfWork:
        return SqlLedgerUnitOfWork(ledger_sessions, platform, fake_clock)

    with use_context(ctx):
        opened = await OpenAccount(uow_factory, fake_clock)(
            OpenAccountCommand(name="Cash", currency="USD")
        )
    relay = OutboxRelay(ledger_sessions, platform, publisher, fake_clock)
    for _ in range(MAX_RELAY_RUNS):
        if await relay.run_once() == 0:
            break
    else:
        pytest.fail("outbox backlog not drained")

    seen = asyncio.Event()

    async def seen_handler(envelope: EventEnvelope, uow: SqlLedgerUnitOfWork) -> None:
        if envelope.tenant_id != tenant:  # other tests' events: leave their tenants untouched
            return
        await handle(envelope, uow)
        if envelope.payload["account_id"] == str(opened.id):
            seen.set()

    consumer = KafkaInboxConsumer(
        kafka_bootstrap,
        f"test-{uuid4()}",
        [TOPIC],
        consumer=CONSUMER,
        handler=seen_handler,
        uow_factory=uow_factory,
        tables=platform,
        clock=fake_clock,
    )
    stop = asyncio.Event()
    consuming = asyncio.create_task(consumer.run(stop))
    waiting = asyncio.create_task(seen.wait())
    try:
        # Whichever ends first: the event is seen, or the consumer dies (its error surfaces).
        await asyncio.wait(
            [consuming, waiting],
            timeout=HANDLED_TIMEOUT_SECONDS,
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        stop.set()
        waiting.cancel()
        await consuming  # run() finishes the in-flight message, so its commit has happened
    assert seen.is_set(), f"AccountOpened not handled within {HANDLED_TIMEOUT_SECONDS}s"

    with use_context(ctx):
        async with uow_factory() as uow:
            assert await uow.stats.count() == 1
    assert await inbox_has(CONSUMER, await outbox_event_id(opened.id))
