"""Transactional outbox writer (A11): events are rows in the same transaction as the change."""

from __future__ import annotations

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from sb_db.lifecycle import FINISHED
from sb_db.platform import PlatformTables
from sb_kernel.clock import Clock
from sb_kernel.context import RequestContext
from sb_kernel.events import DomainEvent
from sb_kernel.ids import new_id


class SqlOutbox:
    """Buffers events during the use case; the UoW flushes them just before commit."""

    def __init__(self, tables: PlatformTables, ctx: RequestContext, clock: Clock) -> None:
        self._tables, self._ctx, self._clock = tables, ctx, clock
        self._pending: list[DomainEvent] = []
        self._closed = False

    def close(self) -> None:
        """Drop anything buffered; later adds raise (the unit of work is finished)."""
        self._pending.clear()
        self._closed = True

    def add(self, event: DomainEvent) -> None:
        if self._closed:
            raise RuntimeError(FINISHED)
        self._pending.append(event)

    async def flush(self, session: AsyncSession) -> None:
        for event in self._pending:
            kind = type(event)
            await session.execute(
                insert(self._tables.outbox).values(
                    event_id=new_id(),
                    tenant_id=self._ctx.tenant_id,
                    topic=kind.topic(),
                    key=event.event_key(),
                    payload=event.model_dump(mode="json"),
                    headers={
                        "event_type": kind.event_type,
                        "schema_version": kind.schema_version,
                        "request_id": self._ctx.request_id,
                        "trace_id": self._ctx.trace_id,
                        "actor": self._ctx.actor,
                    },
                    occurred_at=self._clock.now(),
                )
            )
        self._pending.clear()
