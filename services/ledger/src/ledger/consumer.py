"""`python -m ledger.consumer`: the outbox relay and the inbox consumer in one process.

Two tasks share one `asyncio.TaskGroup` until SIGTERM or SIGINT sets `stop`:
- the relay loop (D12): `OutboxRelay.run_once()` moves outbox rows to Kafka; when a run finds
  nothing it waits up to a second (or until `stop`) before the next;
- the `KafkaInboxConsumer` (D11), which applies `AccountOpened` through
  `interface.consumers.account_opened.handle`.

A handler error or a fatal `PublishFailed` ends its task; the `TaskGroup` cancels the other and
the process exits non-zero, so its supervisor (compose `restart`, Kubernetes) restarts it with a
fresh producer and consumer. Nothing here catches and loops. Importing this module builds nothing.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys
from typing import Protocol

from ledger.bootstrap import build_container
from ledger.infrastructure.models import platform
from ledger.infrastructure.settings import Settings, load_settings
from ledger.interface.consumers.account_opened import CONSUMER, TOPIC, handle
from sb_messaging.consumer import KafkaInboxConsumer
from sb_messaging.publisher import KafkaPublisher
from sb_messaging.relay import OutboxRelay
from sb_obs.logging import configure_logging, get_logger

__all__ = ["main", "relay_loop", "run"]

RELAY_CLIENT_ID = "ledger-relay"
CONSUMER_GROUP = "ledger"
PUBLISH_TIMEOUT_SECONDS = 10.0
RELAY_BATCH_SIZE = 100
RELAY_IDLE_SECONDS = 1.0

_log = get_logger(__name__)


class Relay(Protocol):
    """What the loop needs from `OutboxRelay` (a seam for its unit tests)."""

    async def run_once(self) -> int: ...


async def relay_loop(relay: Relay, stop: asyncio.Event) -> None:
    while not stop.is_set():
        if await relay.run_once() == 0:  # a fatal PublishFailed propagates: let it (D12)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=RELAY_IDLE_SECONDS)


async def run(settings: Settings) -> None:
    container = build_container(settings)
    publisher: KafkaPublisher | None = None
    try:
        publisher = KafkaPublisher(
            settings.kafka_bootstrap, RELAY_CLIENT_ID, timeout_seconds=PUBLISH_TIMEOUT_SECONDS
        )
        relay = OutboxRelay(
            container.sessions, platform, publisher, container.clock, batch_size=RELAY_BATCH_SIZE
        )
        consumer = KafkaInboxConsumer(
            settings.kafka_bootstrap,
            CONSUMER_GROUP,
            [TOPIC],
            consumer=CONSUMER,
            handler=handle,
            uow_factory=container.uow_factory,
            tables=platform,
            clock=container.clock,
        )
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(relay_loop(relay, stop))
            tasks.create_task(consumer.run(stop))
    finally:
        try:
            if publisher is not None:
                await asyncio.to_thread(publisher.close)
        finally:
            await container.engine.dispose()


def main() -> None:
    settings = load_settings()
    configure_logging(level=settings.log_level)  # D19: this process's own entrypoint
    try:
        asyncio.run(run(settings))
    except BaseExceptionGroup as group:  # a task failed: exit so the supervisor restarts us
        _log.error(
            "ledger.consumer.exited",
            errors=[f"{type(exc).__name__}: {exc}" for exc in group.exceptions],
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
