"""Transactional-outbox relay (A11): unpublished outbox rows → Kafka, at least once.

- Tenancy: it runs across tenants, so it uses a plain session (no unit of work, no tenant).
  The outbox has no RLS.
- Single active: each run first takes `pg_try_advisory_xact_lock(hashtext('sb_outbox_relay'))`
  in its transaction and returns 0 without it. Replicas are therefore safe, and only one
  publishes at a time, so rows go out in outbox id order. `FOR UPDATE SKIP LOCKED`
  additionally keeps rows that some other writer has locked out of the batch.
- Ordering: id order is per-key order only if the ids of one key are assigned in commit order,
  which needs a single writer per key. Concurrent transactions writing the same key can commit
  out of id order (see docs/architecture/messaging.md).
- Delivery: a crash after a publish but before the commit re-sends that row on the next run.
  Consumers dedupe on `event_id` through the inbox.
- Transaction length: bounded by `batch_size` times the publisher's per-message timeout (for
  `KafkaPublisher`, `timeout_seconds` plus a flush grace). Row locks are held that long, so
  keep the batch small enough for your lock and statement budgets.
- Failures: `PublishFailed` stops the batch. So does a row that cannot become an envelope (a
  poison row), which is logged at error level as `outbox.row_unpublishable`. Either way the
  rows already published are committed as published, and the next run starts at the failed
  row. A poison row therefore blocks the relay until someone fixes or removes it. Parking or
  quarantining it needs a schema change (e.g. a `failed_at`/`last_error` column); that is a
  ledgered follow-up. A fatal `PublishFailed` (the producer is unusable) is re-raised after
  that commit, so the process exits and its supervisor restarts it with a new producer.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from sqlalchemy import RowMapping, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sb_db.platform import PlatformTables
from sb_kernel.clock import Clock
from sb_messaging.envelope import EventEnvelope
from sb_messaging.publisher import Publisher, PublishFailed
from sb_obs.logging import get_logger

_log = get_logger(__name__)

RELAY_LOCK = "sb_outbox_relay"


def _envelope(row: RowMapping) -> EventEnvelope:
    headers: Mapping[str, Any] = row["headers"]
    return EventEnvelope(
        event_id=row["event_id"],
        event_type=headers["event_type"],
        schema_version=headers["schema_version"],
        topic=row["topic"],
        key=row["key"],
        occurred_at=row["occurred_at"],
        tenant_id=row["tenant_id"],
        actor=headers["actor"],
        request_id=headers["request_id"],
        trace_id=headers.get("trace_id"),
        payload=row["payload"],
    )


class OutboxRelay:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        tables: PlatformTables,
        publisher: Publisher,
        clock: Clock,
        *,
        batch_size: int = 100,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self._sessions, self._tables, self._publisher, self._clock = (
            sessions,
            tables,
            publisher,
            clock,
        )
        self._batch_size = batch_size

    async def run_once(self) -> int:
        """Publish up to one batch in id order; return how many rows were published."""
        outbox = self._tables.outbox
        published = 0
        fatal: PublishFailed | None = None
        async with self._sessions() as session, session.begin():
            if not await self._lock(session):
                return 0
            rows = (
                (
                    await session.execute(
                        select(outbox)
                        .where(outbox.c.published_at.is_(None))
                        .order_by(outbox.c.id)
                        .limit(self._batch_size)
                        .with_for_update(skip_locked=True)
                    )
                )
                .mappings()
                .all()
            )
            for row in rows:
                try:
                    if not await self._publish(row):
                        break
                except PublishFailed as exc:  # fatal: commit the marks made so far, then raise
                    fatal = exc
                    break
                await session.execute(
                    update(outbox)
                    .where(outbox.c.id == row["id"])
                    .values(published_at=self._clock.now())
                )
                published += 1
        if fatal is not None:
            raise fatal
        return published

    @staticmethod
    async def _lock(session: AsyncSession) -> bool:
        acquired = await session.execute(
            text("SELECT pg_try_advisory_xact_lock(hashtext(:name))"), {"name": RELAY_LOCK}
        )
        return bool(acquired.scalar_one())

    async def _publish(self, row: RowMapping) -> bool:
        """Publish one row; False (logged) means stop the batch here.

        A fatal `PublishFailed` is logged and re-raised.
        """
        try:
            envelope = _envelope(row)
            await asyncio.to_thread(
                self._publisher.publish,
                envelope.topic,
                envelope.key.encode(),
                envelope.to_bytes(),
            )
        except PublishFailed as exc:
            _log.warning(
                "outbox.publish_failed",
                outbox_id=row["id"],
                event_id=str(row["event_id"]),
                topic=row["topic"],
                fatal=exc.fatal,
                exc=str(exc),
            )
            if exc.fatal:
                raise
            return False
        except Exception as exc:  # a poison row: it can never become an envelope
            _log.error("outbox.row_unpublishable", outbox_id=row["id"], exc=repr(exc))
            return False
        return True
