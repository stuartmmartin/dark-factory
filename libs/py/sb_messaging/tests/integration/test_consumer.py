"""KafkaInboxConsumer failure paths: nothing is lost, poison is a policy, commits may fail."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

import pytest
import structlog
from confluent_kafka import OFFSET_INVALID, KafkaError, KafkaException, Message
from pydantic import ValidationError
from sqlalchemy import Table, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sb_db.platform import PlatformTables
from sb_db.uow import SqlAlchemyUnitOfWork
from sb_kernel.context import current_context
from sb_messaging.consumer import KafkaInboxConsumer
from sb_messaging.envelope import EventEnvelope
from sb_messaging.publisher import KafkaPublisher
from sb_testing.clock import FakeClock

type Sessions = async_sessionmaker[AsyncSession]

RUN_TIMEOUT_SECONDS = 60


def _envelope(event_type: str) -> EventEnvelope:
    return EventEnvelope(
        event_id=uuid4(),
        event_type=event_type,
        schema_version=1,
        topic=f"{event_type}.v1",
        key="k",
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        tenant_id=uuid4(),
        actor="alice",
        request_id="r1",
        trace_id=None,
        payload={},
    )


class Harness:
    """Builds consumers for one topic and group, with a handler that records effects."""

    def __init__(
        self,
        *,
        bootstrap: str,
        topic: str,
        sessions: Sessions,
        platform: PlatformTables,
        effects: Table,
        clock: FakeClock,
    ) -> None:
        self.bootstrap, self.topic, self.group = bootstrap, topic, f"{topic}-group"
        self.platform, self.clock = platform, clock
        self._sessions, self._effects = sessions, effects
        self.handled: list[UUID] = []
        self.fail_first = False
        self.stop = asyncio.Event()

    def new_uow(self) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(self._sessions, self.platform, self.clock)

    async def handler(self, envelope: EventEnvelope, uow: SqlAlchemyUnitOfWork) -> None:
        self.handled.append(envelope.event_id)
        await uow.session.execute(
            insert(self._effects).values(
                event_id=envelope.event_id, tenant_id=current_context().tenant_id
            )
        )
        if self.fail_first and len(self.handled) == 1:
            raise RuntimeError("handler failed after writing")  # the write must roll back
        self.stop.set()

    def consumer(self, **extra: Any) -> KafkaInboxConsumer[SqlAlchemyUnitOfWork]:
        return KafkaInboxConsumer(
            self.bootstrap,
            self.group,
            [self.topic],
            consumer="it-consumer",
            handler=self.handler,
            uow_factory=self.new_uow,
            tables=self.platform,
            clock=self.clock,
            poll_timeout=0.5,
            **extra,
        )

    async def run(self, consumer: KafkaInboxConsumer[SqlAlchemyUnitOfWork]) -> None:
        self.stop.clear()
        await asyncio.wait_for(consumer.run(self.stop), timeout=RUN_TIMEOUT_SECONDS)


@pytest.fixture
def harness(
    *,
    kafka_bootstrap: str,
    create_topic: Callable[[str], None],
    app_sessions: Sessions,
    platform: PlatformTables,
    effects_table: Table,
    fake_clock: FakeClock,
    request: pytest.FixtureRequest,
) -> Harness:
    topic = f"test.{request.node.name.replace('_', '-')}.v1"  # pyright: ignore[reportUnknownMemberType]
    create_topic(topic)
    return Harness(
        bootstrap=kafka_bootstrap,
        topic=topic,
        sessions=app_sessions,
        platform=platform,
        effects=effects_table,
        clock=fake_clock,
    )


async def _effects(sessions: Sessions, effects: Table) -> list[UUID]:
    async with sessions() as session:
        return list((await session.execute(select(effects.c.event_id))).scalars())


async def test_handler_failure_loses_nothing(
    *,
    harness: Harness,
    publisher: KafkaPublisher,
    admin_sessions: Sessions,
    effects_table: Table,
    group_offset: Callable[[str, str], int],
) -> None:
    env = _envelope(harness.topic.removesuffix(".v1"))
    publisher.publish(harness.topic, b"k", env.to_bytes())
    harness.fail_first = True

    with pytest.raises(RuntimeError, match="handler failed"):
        await harness.run(harness.consumer())

    assert group_offset(harness.group, harness.topic) == OFFSET_INVALID  # not advanced
    assert await _effects(admin_sessions, effects_table) == []  # rolled back

    await harness.run(harness.consumer())  # a fresh consumer in the same group

    assert harness.handled == [env.event_id, env.event_id]  # redelivered
    assert await _effects(admin_sessions, effects_table) == [env.event_id]  # applied once
    assert group_offset(harness.group, harness.topic) == 1  # now past the message


async def test_undecodable_message_raises_by_default(
    *, harness: Harness, publisher: KafkaPublisher, group_offset: Callable[[str, str], int]
) -> None:
    publisher.publish(harness.topic, b"k", b"not an envelope")

    with pytest.raises(ValidationError):
        await harness.run(harness.consumer())

    assert group_offset(harness.group, harness.topic) == OFFSET_INVALID


async def test_skip_policy_commits_past_undecodable_message(
    *,
    harness: Harness,
    publisher: KafkaPublisher,
    admin_sessions: Sessions,
    effects_table: Table,
    group_offset: Callable[[str, str], int],
) -> None:
    env = _envelope(harness.topic.removesuffix(".v1"))
    publisher.publish(harness.topic, b"k", b"not an envelope")
    publisher.publish(harness.topic, b"k", env.to_bytes())
    poisoned: list[tuple[int | None, type[Exception]]] = []

    async def skip(msg: Message, exc: Exception) -> Literal["raise", "skip"]:
        poisoned.append((msg.offset(), type(exc)))
        return "skip"

    with structlog.testing.capture_logs() as logs:
        await harness.run(harness.consumer(on_poison=skip))

    assert poisoned == [(0, ValidationError)]
    assert "kafka.message_undecodable" in [entry["event"] for entry in logs]
    assert harness.handled == [env.event_id]
    assert await _effects(admin_sessions, effects_table) == [env.event_id]
    assert group_offset(harness.group, harness.topic) == 2


class FlakyCommitKafka:
    """A Kafka consumer double: serves fixed messages; the first commit fails."""

    def __init__(self, messages: list[Message]) -> None:
        self._messages = messages
        self.commits: list[int | None] = []

    def subscribe(self, topics: list[str]) -> None:
        del topics

    def poll(self, timeout: float) -> Message | None:
        del timeout
        return self._messages.pop(0) if self._messages else None

    def commit(self, *, message: Message, asynchronous: Literal[False]) -> object:
        del asynchronous
        self.commits.append(message.offset())
        if len(self.commits) == 1:
            raise KafkaException(KafkaError(KafkaError._TRANSPORT, "coordinator gone"))
        return None

    def close(self) -> None:
        pass


async def test_commit_failure_is_logged_and_the_loop_continues(
    *, harness: Harness, admin_sessions: Sessions, effects_table: Table
) -> None:
    first, second = _envelope("test.flaky"), _envelope("test.flaky")
    kafka = FlakyCommitKafka(
        [
            Message(topic="test.flaky.v1", partition=0, offset=0, value=first.to_bytes()),
            Message(topic="test.flaky.v1", partition=0, offset=1, value=second.to_bytes()),
        ]
    )
    stop = asyncio.Event()

    async def handler(envelope: EventEnvelope, uow: SqlAlchemyUnitOfWork) -> None:
        await harness.handler(envelope, uow)
        if envelope.event_id == second.event_id:
            stop.set()

    consumer = KafkaInboxConsumer(
        "unused:9092",
        "g",
        ["test.flaky.v1"],
        consumer="it-flaky",
        handler=handler,
        uow_factory=harness.new_uow,
        tables=harness.platform,
        clock=harness.clock,
        kafka_factory=lambda _config: kafka,
    )

    with structlog.testing.capture_logs() as logs:
        await asyncio.wait_for(consumer.run(stop), timeout=RUN_TIMEOUT_SECONDS)

    assert kafka.commits == [0, 1]
    assert "kafka.commit_failed" in [entry["event"] for entry in logs]
    assert harness.handled == [first.event_id, second.event_id]
    assert sorted(await _effects(admin_sessions, effects_table)) == sorted(
        [first.event_id, second.event_id]
    )


class DrainingKafka:
    """A Kafka consumer double: serves fixed messages, then sets `stop` once drained."""

    def __init__(self, messages: list[Message], stop: asyncio.Event) -> None:
        self._messages, self._stop = messages, stop
        self._loop = asyncio.get_running_loop()
        self.commits: list[int | None] = []

    def subscribe(self, topics: list[str]) -> None:
        del topics

    def poll(self, timeout: float) -> Message | None:
        del timeout
        if self._messages:
            return self._messages.pop(0)
        self._loop.call_soon_threadsafe(self._stop.set)  # poll() runs in a worker thread
        return None

    def commit(self, *, message: Message, asynchronous: Literal[False]) -> object:
        del asynchronous
        self.commits.append(message.offset())
        return None

    def close(self) -> None:
        pass


async def test_processed_message_is_logged_without_payload(*, harness: Harness) -> None:
    env = _envelope("test.logged").model_copy(update={"payload": {"secret": "s3cr3t"}})
    stop = asyncio.Event()
    kafka = DrainingKafka(
        [
            Message(topic="test.logged.v1", partition=2, offset=7, value=env.to_bytes()),
            Message(topic="test.logged.v1", partition=2, offset=8, value=env.to_bytes()),
        ],
        stop,
    )
    consumer = KafkaInboxConsumer(
        "unused:9092",
        "g",
        ["test.logged.v1"],
        consumer="it-logged",
        handler=harness.handler,
        uow_factory=harness.new_uow,
        tables=harness.platform,
        clock=harness.clock,
        kafka_factory=lambda _config: kafka,
    )

    with structlog.testing.capture_logs() as logs:
        await asyncio.wait_for(consumer.run(stop), timeout=RUN_TIMEOUT_SECONDS)

    assert kafka.commits == [7, 8]
    processed = [e for e in logs if e["event"] == "kafka.message_processed"]
    assert processed == [
        {
            "event": "kafka.message_processed",
            "log_level": "info",
            "consumer": "it-logged",
            "event_id": str(env.event_id),
            "topic": "test.logged.v1",
            "partition": 2,
            "offset": 7,
        }
    ]
    # The redelivery is a duplicate, not a second "processed".
    assert [e["event"] for e in logs if e["event"].startswith("kafka.message_")] == [
        "kafka.message_processed",
        "kafka.message_duplicate",
    ]
    assert "s3cr3t" not in repr(logs)
