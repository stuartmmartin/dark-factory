"""`process()` against fakes: the inbox is a set, the unit of work stages until commit (T3)."""

from datetime import UTC, datetime
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4

import pytest
from sqlalchemy import MetaData

from sb_db.platform import PlatformTables, install_platform_tables
from sb_kernel.context import current_context
from sb_messaging.envelope import EventEnvelope
from sb_messaging.inbox import process
from sb_testing.clock import FakeClock

CONSUMER = "ledger-projector"
TABLES: PlatformTables = install_platform_tables(MetaData())


def _envelope(**over: object) -> EventEnvelope:
    data: dict[str, object] = {
        "event_id": uuid4(),
        "event_type": "ledger.journal_entry.posted",
        "schema_version": 1,
        "topic": "ledger.journal_entry.posted.v1",
        "key": "k",
        "occurred_at": datetime(2026, 1, 1, tzinfo=UTC),
        "tenant_id": uuid4(),
        "actor": "alice",
        "request_id": "r1",
        "trace_id": None,
        "payload": {"amount": "1.00"},
    }
    data.update(over)
    return EventEnvelope.model_validate(data)


class FakeUow:
    """`seen` is the committed inbox; inbox rows staged in this UoW land there only on commit."""

    def __init__(self, seen: set[tuple[str, UUID]]) -> None:
        self.seen = seen
        self.staged: set[tuple[str, UUID]] = set()
        self.committed = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if not self.committed:
            await self.rollback()

    async def commit(self) -> None:
        self.seen |= self.staged
        self.staged.clear()
        self.committed = True

    async def rollback(self) -> None:
        self.staged.clear()


async def fake_record_inbox(uow: FakeUow, consumer: str, event_id: UUID) -> bool:
    """Like INSERT ... ON CONFLICT DO NOTHING RETURNING: True only for a first sighting."""
    entry = (consumer, event_id)
    if entry in uow.seen or entry in uow.staged:
        return False
    uow.staged.add(entry)
    return True


class Recorder:
    def __init__(self, *, fail: bool = False) -> None:
        self.handler_calls: list[EventEnvelope] = []
        self.tenants: list[UUID] = []
        self._fail = fail

    async def __call__(self, envelope: EventEnvelope, uow: FakeUow) -> None:
        del uow
        self.handler_calls.append(envelope)
        self.tenants.append(current_context().tenant_id)
        if self._fail:
            raise RuntimeError("handler exploded")


async def _process(
    envelope: EventEnvelope, uow: FakeUow, handler: Recorder, clock: FakeClock
) -> bool:
    return await process(
        envelope,
        consumer=CONSUMER,
        handler=handler,
        uow_factory=lambda: uow,
        tables=TABLES,
        clock=clock,
        record_inbox=fake_record_inbox,
    )


async def test_first_delivery_runs_handler_and_commits(fake_clock: FakeClock) -> None:
    env = _envelope()
    uow, handler = FakeUow(set()), Recorder()

    applied = await _process(env, uow, handler, fake_clock)

    assert applied is True
    assert handler.handler_calls == [env]
    assert uow.committed is True
    assert uow.seen == {(CONSUMER, env.event_id)}


async def test_duplicate_delivery_skips_handler(fake_clock: FakeClock) -> None:
    env = _envelope()
    uow, handler = FakeUow({(CONSUMER, env.event_id)}), Recorder()

    applied = await _process(env, uow, handler, fake_clock)

    assert applied is False
    assert handler.handler_calls == []
    assert uow.committed is False


async def test_same_event_for_another_consumer_is_not_a_duplicate(fake_clock: FakeClock) -> None:
    env = _envelope()
    uow, handler = FakeUow({("some-other-consumer", env.event_id)}), Recorder()

    applied = await _process(env, uow, handler, fake_clock)

    assert applied is True
    assert handler.handler_calls == [env]
    assert uow.committed is True


async def test_handler_failure_does_not_commit_or_mark_seen(fake_clock: FakeClock) -> None:
    env = _envelope()
    uow, handler = FakeUow(set()), Recorder(fail=True)

    with pytest.raises(RuntimeError, match="handler exploded"):
        await _process(env, uow, handler, fake_clock)

    assert handler.handler_calls == [env]
    assert uow.committed is False
    assert uow.seen == set()
    # ...so a redelivery is applied, not skipped.
    retry_uow, retry_handler = FakeUow(uow.seen), Recorder()
    assert await _process(env, retry_uow, retry_handler, fake_clock) is True
    assert retry_handler.handler_calls == [env]
    assert retry_uow.committed is True


async def test_handler_runs_inside_envelope_context(fake_clock: FakeClock) -> None:
    env = _envelope()
    uow, handler = FakeUow(set()), Recorder()

    await _process(env, uow, handler, fake_clock)

    assert handler.tenants == [env.tenant_id]
    assert uow.committed is True
