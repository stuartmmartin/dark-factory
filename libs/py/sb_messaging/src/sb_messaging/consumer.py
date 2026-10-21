"""Kafka consumer loop: poll → `process` (inbox-deduped) → commit the offset (A11).

Offsets are committed manually, only after the message's transaction has committed, so a crash
anywhere re-delivers rather than loses. The inbox makes that redelivery a no-op.

Failure policy:
- A handler error is logged (`kafka.message_failed`) and re-raised. That stops the loop
  without committing: skipping would let the next offset commit past the message and lose it.
  The supervisor restarts the consumer, which resumes at the failed message.
- Undecodable bytes (not a valid `EventEnvelope`) are logged (`kafka.message_undecodable`)
  and handed to `on_poison`. The default re-raises, as above. `"skip"` commits past the
  message and continues. A dead-letter topic is a ledgered follow-up.
- A failed offset commit is logged (`kafka.commit_failed`) and the loop continues. At worst
  the message is redelivered, and the inbox makes that harmless.

Shutdown: set the `stop` event. It is checked between messages, so the message in hand
finishes, and then the consumer closes (leaving the group cleanly). Cancelling the task also
closes the client, but only after the in-flight `poll()` returns, because librdkafka must not
close a handle that is still polling. A message fetched by that poll is not committed, so it
is redelivered. `close()` itself is bounded by `close_timeout` (C6): if it hangs (e.g. an
unreachable group coordinator), `kafka.close_timed_out` is logged and `run()` returns, leaving
the close to finish in its thread.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal, Protocol

from confluent_kafka import Consumer, KafkaException, Message
from pydantic import ValidationError

from sb_db.platform import PlatformTables
from sb_db.uow import SqlAlchemyUnitOfWork
from sb_kernel.clock import Clock
from sb_messaging.envelope import EventEnvelope
from sb_messaging.inbox import process
from sb_obs.logging import get_logger

_log = get_logger(__name__)

# Bounds each broker request (fetch, offset commit, group coordination) (C6).
SOCKET_TIMEOUT_MS = 10_000
CLOSE_TIMEOUT_SECONDS = 10.0

type PoisonDecision = Literal["raise", "skip"]
type OnPoison = Callable[[Message, Exception], Awaitable[PoisonDecision]]


class KafkaConsumerLike(Protocol):
    """The part of `confluent_kafka.Consumer` the loop uses (a seam for unit tests)."""

    def subscribe(self, topics: list[str]) -> None: ...

    def poll(self, timeout: float) -> Message | None: ...

    def commit(self, *, message: Message, asynchronous: Literal[False]) -> object: ...

    def close(self) -> None: ...


class KafkaInboxConsumer[U: SqlAlchemyUnitOfWork]:
    def __init__(
        self,
        bootstrap: str,
        group_id: str,
        topics: Sequence[str],
        *,
        consumer: str,
        handler: Callable[[EventEnvelope, U], Awaitable[None]],
        uow_factory: Callable[[], U],
        tables: PlatformTables,
        clock: Clock,
        poll_timeout: float = 1.0,
        on_poison: OnPoison | None = None,
        close_timeout: float = CLOSE_TIMEOUT_SECONDS,
        kafka_factory: Callable[[dict[str, Any]], KafkaConsumerLike] = Consumer,
    ) -> None:
        self._config: dict[str, Any] = {
            "bootstrap.servers": bootstrap,
            "group.id": group_id,
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
            "socket.timeout.ms": SOCKET_TIMEOUT_MS,
        }
        self._topics = list(topics)
        self._consumer_name = consumer
        self._handler, self._uow_factory, self._tables, self._clock = (
            handler,
            uow_factory,
            tables,
            clock,
        )
        self._poll_timeout = poll_timeout
        self._on_poison = on_poison
        self._close_timeout = close_timeout
        self._kafka_factory = kafka_factory

    async def run(self, stop: asyncio.Event) -> None:
        """Consume until `stop` is set (checked between messages)."""
        kafka = self._kafka_factory(self._config)
        polling: asyncio.Future[Message | None] | None = None
        try:
            kafka.subscribe(self._topics)
            while not stop.is_set():
                polling = asyncio.ensure_future(asyncio.to_thread(kafka.poll, self._poll_timeout))
                msg = await asyncio.shield(polling)
                if msg is not None and await self._handle(msg):
                    await self._commit(kafka, msg)
        finally:
            if polling is not None and not polling.done():
                await asyncio.wait([polling])  # never close() under a running poll()
            await self._close(kafka)

    async def _close(self, kafka: KafkaConsumerLike) -> None:
        closing = asyncio.ensure_future(asyncio.to_thread(kafka.close))
        done, _ = await asyncio.wait([closing], timeout=self._close_timeout)
        if not done:
            _log.warning(
                "kafka.close_timed_out",
                consumer=self._consumer_name,
                timeout_seconds=self._close_timeout,
            )
            return
        closing.result()  # re-raise a failed close

    async def _handle(self, msg: Message) -> bool:
        """Apply one message; True when its offset may be committed."""
        error = msg.error()
        if error is not None:
            _log.warning("kafka.consumer_error", error=str(error), fatal=error.fatal())
            if error.fatal():  # the client instance is unusable
                raise KafkaException(error)
            return False  # transient (broker down, rebalance); librdkafka recovers
        where = {"topic": msg.topic(), "partition": msg.partition(), "offset": msg.offset()}
        try:
            envelope = EventEnvelope.from_bytes(msg.value() or b"")
        except ValidationError as exc:
            _log.error("kafka.message_undecodable", consumer=self._consumer_name, **where)
            decision = "raise" if self._on_poison is None else await self._on_poison(msg, exc)
            if decision == "raise":
                raise
            return True
        try:
            applied = await process(
                envelope,
                consumer=self._consumer_name,
                handler=self._handler,
                uow_factory=self._uow_factory,
                tables=self._tables,
                clock=self._clock,
            )
        except Exception:
            _log.exception("kafka.message_failed", consumer=self._consumer_name, **where)
            raise
        # Identifiers only, never payload fields (they may carry PII).
        _log.info(
            "kafka.message_processed" if applied else "kafka.message_duplicate",
            consumer=self._consumer_name,
            event_id=str(envelope.event_id),
            **where,
        )
        return True

    async def _commit(self, kafka: KafkaConsumerLike, msg: Message) -> None:
        try:
            await asyncio.to_thread(kafka.commit, message=msg, asynchronous=False)
        except KafkaException as exc:
            _log.warning(
                "kafka.commit_failed",
                consumer=self._consumer_name,
                topic=msg.topic(),
                partition=msg.partition(),
                offset=msg.offset(),
                exc=str(exc),
            )
