"""KafkaPublisher against a fake producer (T3): config, delivery outcomes, close."""

from collections.abc import Callable
from typing import Any

import pytest
from confluent_kafka import KafkaError, Message

from sb_messaging.publisher import KafkaPublisher, PublishFailed

type DeliveryCallback = Callable[[KafkaError | None, Message], None]


class FakeProducer:
    """Delivers (or fails) every queued message on flush, like librdkafka's callbacks."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.error: KafkaError | None = None
        self.undelivered = 0
        self.flush_timeouts: list[float] = []
        self.closed = False
        self._queued: list[tuple[DeliveryCallback, Message]] = []

    def produce(
        self, topic: str, value: bytes, key: bytes, *, on_delivery: DeliveryCallback
    ) -> None:
        self._queued.append((on_delivery, Message(topic=topic, key=key, value=value)))

    def flush(self, timeout: float) -> int:
        self.flush_timeouts.append(timeout)
        for callback, msg in self._queued:
            callback(self.error, msg)
        self._queued.clear()
        return self.undelivered

    def close(self) -> None:
        self.closed = True


def _publisher(timeout_seconds: float = 10.0) -> tuple[KafkaPublisher, FakeProducer]:
    made: list[FakeProducer] = []

    def factory(config: dict[str, Any]) -> FakeProducer:
        made.append(FakeProducer(config))
        return made[0]

    publisher = KafkaPublisher(
        "broker:9092", "svc", timeout_seconds=timeout_seconds, producer_factory=factory
    )
    return publisher, made[0]


def test_producer_is_idempotent_and_bounded() -> None:
    _, producer = _publisher(timeout_seconds=5)
    assert producer.config["enable.idempotence"] is True
    assert producer.config["acks"] == "all"
    assert producer.config["message.timeout.ms"] == 5000


def test_flush_waits_past_the_delivery_timeout() -> None:
    """flush outlives message.timeout.ms, so a timed-out delivery reports through the callback."""
    publisher, producer = _publisher(timeout_seconds=5)
    publisher.publish("t.v1", b"k", b"v")
    assert producer.flush_timeouts == [7.0]


def test_delivery_error_raises_publish_failed() -> None:
    publisher, producer = _publisher()
    producer.error = KafkaError(KafkaError._MSG_TIMED_OUT, "timed out")
    with pytest.raises(PublishFailed) as caught:
        publisher.publish("t.v1", b"k", b"v")
    assert caught.value.fatal is False


def test_fatal_producer_error_is_flagged() -> None:
    publisher, producer = _publisher()
    producer.error = KafkaError(KafkaError._FATAL, "fenced", fatal=True)
    with pytest.raises(PublishFailed) as caught:
        publisher.publish("t.v1", b"k", b"v")
    assert caught.value.fatal is True


def test_unacked_messages_raise_publish_failed() -> None:
    publisher, producer = _publisher()
    producer.undelivered = 1
    with pytest.raises(PublishFailed, match="not acked"):
        publisher.publish("t.v1", b"k", b"v")


def test_close_closes_the_producer() -> None:
    publisher, producer = _publisher()
    publisher.close()
    assert producer.closed is True
