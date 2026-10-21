"""Publishing to Kafka: an idempotent producer that blocks until the broker acks (A11, C6)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from confluent_kafka import KafkaError, KafkaException, Message, Producer


class PublishFailed(Exception):  # noqa: N818 - name fixed by the messaging interface
    """The broker did not acknowledge the message; the caller must treat it as unsent.

    `fatal` means the producer instance is unusable (e.g. fenced): build a new one.
    """

    def __init__(self, message: str, *, fatal: bool = False) -> None:
        super().__init__(message)
        self.fatal = fatal


class Publisher(Protocol):
    def publish(self, topic: str, key: bytes, value: bytes) -> None:
        """Block until the broker acks; raise `PublishFailed` otherwise."""
        ...


type DeliveryCallback = Callable[[KafkaError | None, Message], None]


class ProducerLike(Protocol):
    """The part of `confluent_kafka.Producer` the publisher uses (a seam for unit tests)."""

    def produce(
        self, topic: str, value: bytes, key: bytes, *, on_delivery: DeliveryCallback
    ) -> None: ...

    def flush(self, timeout: float) -> int: ...


# flush() outlives message.timeout.ms by this much, so a delivery that times out is reported
# through the callback (with its error) rather than as a bare "still queued" count.
FLUSH_GRACE_SECONDS = 2.0


class KafkaPublisher:
    """`enable.idempotence` + `acks=all`: producer retries never duplicate or reorder a message.

    Blocking (librdkafka flush): call it from a worker thread in async code. `close()` when done.
    """

    def __init__(
        self,
        bootstrap: str,
        client_id: str,
        *,
        timeout_seconds: float = 10.0,
        producer_factory: Callable[[dict[str, Any]], ProducerLike] = Producer,
    ) -> None:
        timeout_ms = int(timeout_seconds * 1000)
        self._flush_timeout = timeout_ms / 1000 + FLUSH_GRACE_SECONDS
        self._producer = producer_factory(
            {
                "bootstrap.servers": bootstrap,
                "client.id": client_id,
                "enable.idempotence": True,
                "acks": "all",
                # Bound delivery (incl. internal retries) and each broker request (C6).
                "message.timeout.ms": timeout_ms,
                "socket.timeout.ms": timeout_ms,
            }
        )

    def publish(self, topic: str, key: bytes, value: bytes) -> None:
        errors: list[KafkaError] = []

        def on_delivery(err: KafkaError | None, msg: Message) -> None:
            del msg
            if err is not None:
                errors.append(err)

        try:
            self._producer.produce(topic, value, key, on_delivery=on_delivery)
        except (BufferError, KafkaException) as exc:  # local queue full / producer error
            raise PublishFailed(f"could not enqueue message for {topic}: {exc}") from exc
        undelivered = self._producer.flush(self._flush_timeout)
        if errors:
            err = errors[0]
            raise PublishFailed(f"delivery to {topic} failed: {err}", fatal=err.fatal())
        if undelivered:
            raise PublishFailed(f"{undelivered} message(s) to {topic} not acked in time")

    def close(self) -> None:
        """Deliver what is still queued (bounded) and release the librdkafka handle."""
        self._producer.flush(self._flush_timeout)
        # Producer.close exists at runtime (confluent-kafka >= 2.x) but not in the 2.15 stubs.
        closer: Callable[[], None] | None = getattr(self._producer, "close", None)
        if closer is not None:
            closer()


class RecordingPublisher:
    """In-memory `Publisher` for tests: keeps what was sent; `fail_after=n` fails the n+1th.

    `fatal=True` makes that failure a fatal `PublishFailed` (an unusable producer).
    """

    def __init__(self, *, fail_after: int | None = None, fatal: bool = False) -> None:
        self.sent: list[tuple[str, bytes, bytes]] = []
        self._fail_after = fail_after
        self._fatal = fatal

    def publish(self, topic: str, key: bytes, value: bytes) -> None:
        if self._fail_after is not None and len(self.sent) >= self._fail_after:
            raise PublishFailed("recording publisher configured to fail", fatal=self._fatal)
        self.sent.append((topic, key, value))
