"""KafkaInboxConsumer shutdown: close() never runs under a poll() still in flight."""

import asyncio
import threading
from typing import Literal

import pytest
import structlog
from confluent_kafka import Message
from sqlalchemy import MetaData

from sb_db.platform import install_platform_tables
from sb_db.uow import SqlAlchemyUnitOfWork
from sb_messaging.consumer import KafkaInboxConsumer
from sb_messaging.envelope import EventEnvelope
from sb_testing.clock import FakeClock

WAIT_SECONDS = 5


class BlockingPollKafka:
    """poll() blocks until released, as librdkafka does for up to poll_timeout."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.polling = threading.Event()
        self.release = threading.Event()

    def subscribe(self, topics: list[str]) -> None:
        del topics

    def poll(self, timeout: float) -> Message | None:
        del timeout
        self.events.append("poll_start")
        self.polling.set()
        self.release.wait(WAIT_SECONDS)
        self.events.append("poll_end")
        return None

    def commit(self, *, message: Message, asynchronous: Literal[False]) -> object:
        del message, asynchronous
        return None

    def close(self) -> None:
        self.events.append("close")


async def _unused_handler(envelope: EventEnvelope, uow: SqlAlchemyUnitOfWork) -> None:
    raise AssertionError(f"no message is delivered: {envelope}, {uow}")


def _unused_uow() -> SqlAlchemyUnitOfWork:
    raise AssertionError("no message is delivered")


async def test_cancel_waits_for_in_flight_poll_before_close(fake_clock: FakeClock) -> None:
    kafka = BlockingPollKafka()
    consumer = KafkaInboxConsumer(
        "unused:9092",
        "g",
        ["t.v1"],
        consumer="c",
        handler=_unused_handler,
        uow_factory=_unused_uow,
        tables=install_platform_tables(MetaData()),
        clock=fake_clock,
        kafka_factory=lambda _config: kafka,
    )
    task = asyncio.create_task(consumer.run(asyncio.Event()))
    assert await asyncio.to_thread(kafka.polling.wait, WAIT_SECONDS)

    task.cancel()
    done, _ = await asyncio.wait([task], timeout=0.2)
    assert not done  # still waiting for poll() to return
    assert "close" not in kafka.events

    kafka.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert kafka.events == ["poll_start", "poll_end", "close"]


class HangingCloseKafka(BlockingPollKafka):
    """close() hangs (e.g. an unreachable coordinator) until released."""

    def __init__(self) -> None:
        super().__init__()
        self.closing = threading.Event()

    def close(self) -> None:
        self.events.append("close")
        self.closing.set()
        self.release.wait(WAIT_SECONDS)


async def test_close_is_bounded_by_close_timeout(fake_clock: FakeClock) -> None:
    kafka = HangingCloseKafka()
    consumer = KafkaInboxConsumer(
        "unused:9092",
        "g",
        ["t.v1"],
        consumer="c",
        handler=_unused_handler,
        uow_factory=_unused_uow,
        tables=install_platform_tables(MetaData()),
        clock=fake_clock,
        close_timeout=0.1,
        kafka_factory=lambda _config: kafka,
    )
    stop = asyncio.Event()
    stop.set()  # no polling: run() goes straight to close()
    try:
        with structlog.testing.capture_logs() as logs:
            async with asyncio.timeout(WAIT_SECONDS / 2):
                await consumer.run(stop)
        assert kafka.closing.is_set()
        assert [e["event"] for e in logs] == ["kafka.close_timed_out"]
    finally:
        kafka.release.set()  # let the abandoned close() thread finish
