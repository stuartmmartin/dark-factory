"""Inbox-deduped processing (A11): at-least-once delivery, effectively-once effects.

The inbox row `(consumer, event_id)` is written in the same transaction as the handler's
business writes. A redelivered event finds its row and is skipped. A failed handler rolls
back both, so the redelivery is applied. Two racing deliveries serialize on the primary key:
the second `INSERT ... ON CONFLICT DO NOTHING` waits for the first to commit or roll back.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import partial
from types import TracebackType
from typing import Protocol, Self, cast, overload
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert

from sb_db.platform import PlatformTables
from sb_db.uow import SqlAlchemyUnitOfWork
from sb_kernel.clock import Clock
from sb_kernel.context import use_context
from sb_messaging.envelope import EventEnvelope

type Handler = Callable[[EventEnvelope, SqlAlchemyUnitOfWork], Awaitable[None]]
type RecordInbox[U] = Callable[[U, str, UUID], Awaitable[bool]]


class InboxUnitOfWork(Protocol):
    """What `process` needs from a unit of work (SqlAlchemyUnitOfWork, or a test fake)."""

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...


async def sql_record_inbox(
    uow: SqlAlchemyUnitOfWork,
    consumer: str,
    event_id: UUID,
    *,
    tables: PlatformTables,
    clock: Clock,
) -> bool:
    """Insert the inbox row in the UoW's transaction; False if this consumer has seen it."""
    inbox = tables.inbox
    inserted = await uow.session.execute(
        insert(inbox)
        .values(consumer=consumer, event_id=event_id, processed_at=clock.now())
        .on_conflict_do_nothing()
        .returning(inbox.c.event_id)
    )
    return inserted.first() is not None


@overload
async def process[U: SqlAlchemyUnitOfWork](
    envelope: EventEnvelope,
    *,
    consumer: str,
    handler: Callable[[EventEnvelope, U], Awaitable[None]],
    uow_factory: Callable[[], U],
    tables: PlatformTables,
    clock: Clock,
) -> bool: ...


@overload
async def process[U: InboxUnitOfWork](
    envelope: EventEnvelope,
    *,
    consumer: str,
    handler: Callable[[EventEnvelope, U], Awaitable[None]],
    uow_factory: Callable[[], U],
    tables: PlatformTables,
    clock: Clock,
    record_inbox: RecordInbox[U],
) -> bool: ...


async def process[U: InboxUnitOfWork](
    envelope: EventEnvelope,
    *,
    consumer: str,
    handler: Callable[[EventEnvelope, U], Awaitable[None]],
    uow_factory: Callable[[], U],
    tables: PlatformTables,
    clock: Clock,
    record_inbox: RecordInbox[U] | None = None,
) -> bool:
    """Apply `envelope` once for `consumer`; False if it was already processed (a duplicate).

    Runs as the envelope's tenant and actor, so the handler's writes are RLS-scoped and
    audited under the identity that raised the event. A handler error propagates, and
    nothing (inbox row included) is committed.

    A handler runs its use case in this transaction by passing it `sb_db.uow.joined(uow)`:
    the use case's own `commit()` is then a no-op and this function makes the one commit.
    """
    # The first overload admits the SQL default only when U is a SqlAlchemyUnitOfWork.
    record = (
        record_inbox
        if record_inbox is not None
        else cast(RecordInbox[U], partial(sql_record_inbox, tables=tables, clock=clock))
    )
    with use_context(envelope.context()):
        async with uow_factory() as uow:
            if not await record(uow, consumer, envelope.event_id):
                return False
            await handler(envelope, uow)
            await uow.commit()
    return True
