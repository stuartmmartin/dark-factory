"""OutboxRelay against real Postgres: order, mapping, locking, failure and poison-row stops."""

from uuid import UUID, uuid4

import pytest
import structlog
from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sb_db.platform import PlatformTables
from sb_db.uow import SqlAlchemyUnitOfWork
from sb_kernel.context import RequestContext, use_context
from sb_kernel.events import DomainEvent
from sb_messaging.envelope import EventEnvelope
from sb_messaging.publisher import PublishFailed, RecordingPublisher
from sb_messaging.relay import OutboxRelay
from sb_testing.clock import FakeClock

type Sessions = async_sessionmaker[AsyncSession]


class ThingHappened(DomainEvent):
    event_type = "test.thing.happened"
    thing_id: str

    def event_key(self) -> str:
        return self.thing_id


async def _write_outbox(
    sessions: Sessions, platform: PlatformTables, clock: FakeClock, tenant: UUID, keys: list[str]
) -> None:
    ctx = RequestContext(tenant_id=tenant, actor="alice", request_id="req-9", trace_id="t-9")
    with use_context(ctx):
        async with SqlAlchemyUnitOfWork(sessions, platform, clock) as uow:
            for key in keys:
                uow.outbox.add(ThingHappened(thing_id=key))
            await uow.commit()


async def _published(sessions: Sessions, platform: PlatformTables) -> dict[str, bool]:
    outbox = platform.outbox
    async with sessions() as session:
        rows = await session.execute(select(outbox.c.key, outbox.c.published_at))
        return {key: at is not None for key, at in rows}


async def test_publishes_in_id_order_as_envelopes(
    app_sessions: Sessions, platform: PlatformTables, fake_clock: FakeClock
) -> None:
    tenant = uuid4()
    await _write_outbox(app_sessions, platform, fake_clock, tenant, ["a", "b", "c"])
    publisher = RecordingPublisher()

    assert await OutboxRelay(app_sessions, platform, publisher, fake_clock).run_once() == 3

    assert [(topic, key) for topic, key, _ in publisher.sent] == [
        ("test.thing.happened.v1", b"a"),
        ("test.thing.happened.v1", b"b"),
        ("test.thing.happened.v1", b"c"),
    ]
    first = EventEnvelope.from_bytes(publisher.sent[0][2])
    assert (first.event_type, first.schema_version, first.topic, first.key) == (
        "test.thing.happened",
        1,
        "test.thing.happened.v1",
        "a",
    )
    assert (first.tenant_id, first.actor, first.request_id, first.trace_id) == (
        tenant,
        "alice",
        "req-9",
        "t-9",
    )
    assert first.payload == {"thing_id": "a"}
    assert first.occurred_at == fake_clock.now()
    assert await _published(app_sessions, platform) == {"a": True, "b": True, "c": True}


async def test_batch_size_limits_one_run(
    app_sessions: Sessions, platform: PlatformTables, fake_clock: FakeClock
) -> None:
    await _write_outbox(app_sessions, platform, fake_clock, uuid4(), ["a", "b", "c"])
    relay = OutboxRelay(app_sessions, platform, RecordingPublisher(), fake_clock, batch_size=2)

    assert [await relay.run_once(), await relay.run_once(), await relay.run_once()] == [2, 1, 0]


async def test_publish_failure_stops_batch_and_keeps_earlier_marks(
    app_sessions: Sessions, platform: PlatformTables, fake_clock: FakeClock
) -> None:
    await _write_outbox(app_sessions, platform, fake_clock, uuid4(), ["a", "b", "c"])
    failing = RecordingPublisher(fail_after=1)

    assert await OutboxRelay(app_sessions, platform, failing, fake_clock).run_once() == 1

    assert [key for _, key, _ in failing.sent] == [b"a"]
    assert await _published(app_sessions, platform) == {"a": True, "b": False, "c": False}
    healthy = RecordingPublisher()
    assert await OutboxRelay(app_sessions, platform, healthy, fake_clock).run_once() == 2
    assert [key for _, key, _ in healthy.sent] == [b"b", b"c"]


async def test_non_fatal_publish_failure_logs_the_event_id_and_topic(
    app_sessions: Sessions, platform: PlatformTables, fake_clock: FakeClock
) -> None:
    await _write_outbox(app_sessions, platform, fake_clock, uuid4(), ["a"])
    with structlog.testing.capture_logs() as logs:
        relay = OutboxRelay(app_sessions, platform, RecordingPublisher(fail_after=0), fake_clock)
        assert await relay.run_once() == 0
    [failed] = [e for e in logs if e["event"] == "outbox.publish_failed"]
    assert failed["topic"] == "test.thing.happened.v1"
    assert isinstance(UUID(failed["event_id"]), UUID)
    assert failed["fatal"] is False


async def test_fatal_publish_failure_commits_earlier_marks_then_raises(
    app_sessions: Sessions, platform: PlatformTables, fake_clock: FakeClock
) -> None:
    await _write_outbox(app_sessions, platform, fake_clock, uuid4(), ["a", "b", "c"])
    fatal = RecordingPublisher(fail_after=1, fatal=True)

    with pytest.raises(PublishFailed) as caught:
        await OutboxRelay(app_sessions, platform, fatal, fake_clock).run_once()

    assert caught.value.fatal is True
    assert await _published(app_sessions, platform) == {"a": True, "b": False, "c": False}


async def test_rows_locked_by_another_relay_are_skipped(
    app_sessions: Sessions, platform: PlatformTables, fake_clock: FakeClock
) -> None:
    await _write_outbox(app_sessions, platform, fake_clock, uuid4(), ["a", "b"])
    outbox = platform.outbox
    publisher = RecordingPublisher()

    async with app_sessions() as other, other.begin():
        await other.execute(select(outbox.c.id).where(outbox.c.key == "a").with_for_update())
        assert await OutboxRelay(app_sessions, platform, publisher, fake_clock).run_once() == 1

    assert [key for _, key, _ in publisher.sent] == [b"b"]


async def test_unpublishable_row_stops_batch_and_keeps_earlier_marks(
    app_sessions: Sessions, platform: PlatformTables, fake_clock: FakeClock
) -> None:
    await _write_outbox(app_sessions, platform, fake_clock, uuid4(), ["a", "b"])
    async with app_sessions() as session, session.begin():
        await session.execute(
            insert(platform.outbox).values(
                event_id=uuid4(),
                tenant_id=uuid4(),
                topic="test.thing.happened.v1",
                key="poison",
                payload={},
                headers={"schema_version": 1},  # no event_type/actor/request_id
                occurred_at=fake_clock.now(),
            )
        )
    publisher = RecordingPublisher()
    relay = OutboxRelay(app_sessions, platform, publisher, fake_clock)

    assert [await relay.run_once(), await relay.run_once()] == [2, 0]

    assert [key for _, key, _ in publisher.sent] == [b"a", b"b"]  # not republished
    assert await _published(app_sessions, platform) == {"a": True, "b": True, "poison": False}


async def test_only_one_relay_publishes_at_a_time(
    app_sessions: Sessions, platform: PlatformTables, fake_clock: FakeClock
) -> None:
    await _write_outbox(app_sessions, platform, fake_clock, uuid4(), ["a"])
    publisher = RecordingPublisher()
    relay = OutboxRelay(app_sessions, platform, publisher, fake_clock)

    async with app_sessions() as active, active.begin():  # stands in for a running relay
        await active.execute(text("SELECT pg_advisory_xact_lock(hashtext('sb_outbox_relay'))"))
        assert await relay.run_once() == 0
        assert publisher.sent == []

    assert await relay.run_once() == 1
