"""Typing smoke test: `process` accepts a service's SqlAlchemyUnitOfWork subclass (pyright)."""

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import async_sessionmaker

from sb_db.platform import install_platform_tables
from sb_db.uow import SqlAlchemyUnitOfWork
from sb_messaging.envelope import EventEnvelope
from sb_messaging.inbox import process
from sb_testing.clock import FakeClock


class LedgerUnitOfWork(SqlAlchemyUnitOfWork):
    """A service UoW with its own repositories (none needed here)."""


async def ledger_handler(envelope: EventEnvelope, uow: LedgerUnitOfWork) -> None:
    del envelope, uow


def test_subclassed_uow_and_handler_type_check(fake_clock: FakeClock) -> None:
    tables = install_platform_tables(MetaData())
    sessions = async_sessionmaker()
    pending = process(
        EventEnvelope.model_validate(
            {
                "event_id": "00000000-0000-0000-0000-000000000001",
                "event_type": "ledger.posted",
                "schema_version": 1,
                "topic": "ledger.posted.v1",
                "key": "k",
                "occurred_at": "2026-01-01T00:00:00Z",
                "tenant_id": "00000000-0000-0000-0000-00000000000a",
                "actor": "alice",
                "request_id": "r1",
                "trace_id": None,
                "payload": {},
            }
        ),
        consumer="ledger",
        handler=ledger_handler,  # takes the subclass, not the base UoW
        uow_factory=lambda: LedgerUnitOfWork(sessions, tables, fake_clock),
        tables=tables,
        clock=fake_clock,
    )
    pending.close()  # the call type-checking is the test; nothing runs against a database
