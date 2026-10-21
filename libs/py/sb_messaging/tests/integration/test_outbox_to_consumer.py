"""Outbox row → relay → real Kafka → consumer applies effect once, even on redelivery."""

import asyncio
from collections.abc import Callable
from uuid import uuid4

from sqlalchemy import Table, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sb_db.platform import PlatformTables
from sb_db.uow import SqlAlchemyUnitOfWork
from sb_kernel.context import RequestContext, current_context, use_context
from sb_kernel.events import DomainEvent
from sb_messaging.consumer import KafkaInboxConsumer
from sb_messaging.envelope import EventEnvelope
from sb_messaging.publisher import KafkaPublisher
from sb_messaging.relay import OutboxRelay
from sb_testing.clock import FakeClock

CONSUMER = "it-projector"
GROUP = "it-projector-group"
RUN_TIMEOUT_SECONDS = 60

type Sessions = async_sessionmaker[AsyncSession]


class JournalPosted(DomainEvent):
    event_type = "test.journal.posted"
    entry_id: str

    def event_key(self) -> str:
        return self.entry_id


TOPIC = JournalPosted.topic()


class TeePublisher:
    """Forwards to Kafka and keeps the exact bytes, so the test can redeliver them."""

    def __init__(self, inner: KafkaPublisher) -> None:
        self.inner = inner
        self.sent: list[tuple[str, bytes, bytes]] = []

    def publish(self, topic: str, key: bytes, value: bytes) -> None:
        self.inner.publish(topic, key, value)
        self.sent.append((topic, key, value))


async def test_duplicate_delivery_produces_one_effect(
    *,
    admin_sessions: Sessions,
    app_sessions: Sessions,
    platform: PlatformTables,
    effects_table: Table,
    fake_clock: FakeClock,
    kafka_bootstrap: str,
    publisher: KafkaPublisher,
    create_topic: Callable[[str], None],
    group_offset: Callable[[str, str], int],
) -> None:
    create_topic(TOPIC)
    tenant = uuid4()
    with use_context(RequestContext(tenant_id=tenant, actor="alice", request_id="req-1")):
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as uow:
            uow.outbox.add(JournalPosted(entry_id="entry-1"))
            await uow.commit()

    # Relay: publishes the row to real Kafka and marks it published.
    tee = TeePublisher(publisher)
    relay = OutboxRelay(app_sessions, platform, tee, fake_clock)
    assert await relay.run_once() == 1
    outbox = platform.outbox
    async with admin_sessions() as session:
        event_id, published_at = (
            await session.execute(
                select(outbox.c.event_id, outbox.c.published_at).where(outbox.c.key == "entry-1")
            )
        ).one()
    assert published_at == fake_clock.now()

    handled: list[EventEnvelope] = []
    stop = asyncio.Event()

    async def handler(envelope: EventEnvelope, uow: SqlAlchemyUnitOfWork) -> None:
        handled.append(envelope)
        if not envelope.payload.get("sentinel"):
            await uow.session.execute(
                insert(effects_table).values(
                    event_id=envelope.event_id, tenant_id=current_context().tenant_id
                )
            )
        stop.set()  # the loop still commits this message's offset before it checks `stop`

    def consumer() -> KafkaInboxConsumer[SqlAlchemyUnitOfWork]:
        return KafkaInboxConsumer(
            kafka_bootstrap,
            GROUP,
            [TOPIC],
            consumer=CONSUMER,
            handler=handler,
            uow_factory=lambda: SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock),
            tables=platform,
            clock=fake_clock,
            poll_timeout=0.5,
        )

    # First delivery: the effect is applied and the offset moves past the message.
    await asyncio.wait_for(consumer().run(stop), timeout=RUN_TIMEOUT_SECONDS)
    assert [e.event_id for e in handled] == [event_id]
    assert group_offset(GROUP, TOPIC) == 1

    # Crash between publish and mark-published: the same bytes are delivered again. A sentinel
    # behind it on the same partition tells us the duplicate has been consumed.
    topic, key, value = tee.sent[0]
    publisher.publish(topic, key, value)
    sentinel = EventEnvelope.from_bytes(value).model_copy(
        update={"event_id": uuid4(), "payload": {"sentinel": True}}
    )
    publisher.publish(TOPIC, key, sentinel.to_bytes())
    stop.clear()
    await asyncio.wait_for(consumer().run(stop), timeout=RUN_TIMEOUT_SECONDS)

    assert [e.event_id for e in handled] == [event_id, sentinel.event_id]  # duplicate skipped
    async with admin_sessions() as session:
        effect_rows = (await session.execute(select(effects_table))).all()
        inbox_count = (
            await session.execute(select(func.count()).select_from(platform.inbox))
        ).scalar_one()
    assert [tuple(row) for row in effect_rows] == [(event_id, tenant)]
    assert inbox_count == 2  # the original and the sentinel, each recorded once
    assert group_offset(GROUP, TOPIC) == 3
    assert await relay.run_once() == 0
