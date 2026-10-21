"""A handler runs a use case inside the inbox transaction through `sb_db.uow.joined` (A11).

The use case keeps its normal shape (`async with self._uow() as uow: ...; await uow.commit()`);
`process()` owns the single real commit, so the business row, its audit event and the inbox row
commit together or not at all.
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import ColumnElement, Table, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sb_db.platform import PlatformTables
from sb_db.uow import SqlAlchemyUnitOfWork, joined
from sb_kernel.context import current_context
from sb_messaging.envelope import EventEnvelope
from sb_messaging.inbox import process
from sb_testing.clock import FakeClock

type Sessions = async_sessionmaker[AsyncSession]

CONSUMER = "joined-test"


class RecordEffect:
    """A use case in the standard shape: its own `async with` and `commit()`. Typing the
    factory as returning an async context manager lets it take `joined(uow)` too."""

    def __init__(
        self, uow: Callable[[], AbstractAsyncContextManager[SqlAlchemyUnitOfWork]], effects: Table
    ) -> None:
        self._uow, self._effects = uow, effects

    async def __call__(self, event_id: UUID) -> None:
        async with self._uow() as uow:
            await uow.session.execute(
                insert(self._effects).values(
                    event_id=event_id, tenant_id=current_context().tenant_id
                )
            )
            uow.audit.record(
                action="effect.record",
                entity_type="effect",
                entity_id=str(event_id),
                before=None,
                after={"event_id": str(event_id)},
            )
            await uow.commit()


def _envelope() -> EventEnvelope:
    return EventEnvelope(
        event_id=uuid4(),
        event_type="test.joined.happened",
        schema_version=1,
        topic="test.joined.happened.v1",
        key="k",
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        tenant_id=uuid4(),
        actor="alice",
        request_id="r1",
        trace_id=None,
        payload={},
    )


async def _counts(
    admin_sessions: Sessions, platform: PlatformTables, effects: Table, event_id: UUID
) -> tuple[int, int, int]:
    async with admin_sessions() as session:

        async def count(table: Table, where: ColumnElement[bool]) -> int:
            query = select(func.count()).select_from(table).where(where)
            return (await session.execute(query)).scalar_one()

        return (
            await count(effects, effects.c.event_id == event_id),
            await count(platform.inbox, platform.inbox.c.event_id == event_id),
            await count(platform.audit_events, platform.audit_events.c.entity_id == str(event_id)),
        )


async def test_use_case_via_joined_commits_with_the_inbox_row(
    app_sessions: Sessions,
    admin_sessions: Sessions,
    platform: PlatformTables,
    effects_table: Table,
    fake_clock: FakeClock,
) -> None:
    envelope = _envelope()

    async def handler(env: EventEnvelope, uow: SqlAlchemyUnitOfWork) -> None:
        await RecordEffect(joined(uow), effects_table)(env.event_id)

    applied = await process(
        envelope,
        consumer=CONSUMER,
        handler=handler,
        uow_factory=lambda: SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock),
        tables=platform,
        clock=fake_clock,
    )
    assert applied is True
    assert await _counts(admin_sessions, platform, effects_table, envelope.event_id) == (1, 1, 1)


async def test_handler_failure_after_the_use_case_persists_nothing_and_redelivery_applies_once(
    app_sessions: Sessions,
    admin_sessions: Sessions,
    platform: PlatformTables,
    effects_table: Table,
    fake_clock: FakeClock,
) -> None:
    envelope = _envelope()
    attempts: list[int] = []

    async def handler(env: EventEnvelope, uow: SqlAlchemyUnitOfWork) -> None:
        attempts.append(1)
        await RecordEffect(joined(uow), effects_table)(env.event_id)
        if len(attempts) == 1:
            raise RuntimeError("handler failed after the business write")

    async def deliver() -> bool:
        return await process(
            envelope,
            consumer=CONSUMER,
            handler=handler,
            uow_factory=lambda: SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock),
            tables=platform,
            clock=fake_clock,
        )

    with pytest.raises(RuntimeError, match="after the business write"):
        await deliver()
    assert await _counts(admin_sessions, platform, effects_table, envelope.event_id) == (0, 0, 0)

    assert await deliver() is True
    assert await deliver() is False  # the duplicate is skipped
    assert await _counts(admin_sessions, platform, effects_table, envelope.event_id) == (1, 1, 1)
    assert len(attempts) == 2
