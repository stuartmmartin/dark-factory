"""SQLAlchemy unit of work: one transaction per use case, tenant set for RLS (A13, A14, A11)."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from types import TracebackType
from typing import Self

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sb_db.audit import SqlAuditLog
from sb_db.idempotency import SqlIdempotencyStore
from sb_db.lifecycle import FINISHED
from sb_db.outbox import SqlOutbox
from sb_db.platform import PlatformTables
from sb_db.rls import TENANT_SETTING
from sb_kernel.clock import Clock
from sb_kernel.context import current_context
from sb_kernel.uow import AuditLog, IdempotencyStore, Outbox


class SqlAlchemyUnitOfWork:
    """Implements `sb_kernel.uow.UnitOfWork`. Services subclass it to add repositories.

    The tenant comes only from the request context and is set transaction-locally
    (`set_config(..., true)`), so it can never leak to the next user of a pooled connection.

    Single use: enter once; after `commit()` or `rollback()` the unit of work is finished and
    further commit/rollback/buffer use raises (a rollback after a commit is a no-op).

    To run a use case inside a transaction someone else owns (a Kafka handler inside the inbox
    transaction), pass it `joined(uow)` instead of a factory.
    """

    session: AsyncSession
    # Typed as the kernel protocols (mutable protocol attributes are invariant); the
    # concrete buffers are kept privately so commit() can flush them.
    audit: AuditLog
    outbox: Outbox
    idempotency: IdempotencyStore
    _audit: SqlAuditLog
    _outbox: SqlOutbox

    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], tables: PlatformTables, clock: Clock
    ) -> None:
        self._sessions, self._tables, self._clock = sessions, tables, clock
        self._entered = False
        self._commit_called = False
        self._committed = False
        self._finished = False
        self._joined = 0  # open `joined()` views: commit/rollback are no-ops while > 0

    @property
    def active(self) -> bool:
        """Entered and not yet finished by commit or rollback."""
        return self._entered and not self._finished

    @asynccontextmanager
    async def joined_view(self) -> AsyncGenerator[Self]:
        """This unit of work, joined rather than re-entered: see `joined`."""
        if not self.active:
            raise RuntimeError("joined view: the outer unit of work is not active")
        self._joined += 1
        try:
            yield self  # an exception propagates, so the owner's transaction rolls back
        finally:
            self._joined -= 1

    async def __aenter__(self) -> Self:
        if self._entered:
            raise RuntimeError("unit of work already entered; create a new one per use case")
        ctx = current_context()  # raises Forbidden before any DB work
        self._entered = True
        session = self._sessions()
        try:
            await session.begin()
            await session.execute(
                text("SELECT set_config(:k, :v, true)"),
                {"k": TENANT_SETTING, "v": str(ctx.tenant_id)},
            )
        except BaseException:
            await session.close()
            raise
        self.session = session
        self.audit = self._audit = SqlAuditLog(self._tables, ctx, self._clock)
        self.outbox = self._outbox = SqlOutbox(self._tables, ctx, self._clock)
        self.idempotency = SqlIdempotencyStore(session, self._tables, ctx, self._clock)
        return self

    async def commit(self) -> None:
        if self._joined:  # a joined use case "commits": the owner of the transaction decides
            return
        if self._finished:
            raise RuntimeError(FINISHED)
        self._finished = self._commit_called = True  # a failed commit: __aexit__ rolls back
        try:
            await self._audit.flush(self.session)
            await self._outbox.flush(self.session)
            await self.session.commit()
            self._committed = True
        finally:
            self._close_buffers()

    async def rollback(self) -> None:
        if self._joined:  # a joined use case must raise to abort; see `joined`
            return
        if self._commit_called:  # no-op after commit (a failed one is rolled back on exit)
            return
        if self._finished:
            raise RuntimeError(FINISHED)
        self._finished = True
        self._close_buffers()
        await self.session.rollback()

    def _close_buffers(self) -> None:
        self._audit.close()
        self._outbox.close()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            if not self._committed:
                self._finished = True
                self._close_buffers()
                await self.session.rollback()
        finally:
            await self.session.close()


def joined[U: SqlAlchemyUnitOfWork](uow: U) -> Callable[[], AbstractAsyncContextManager[U]]:
    """A uow factory that joins the already-open `uow` instead of opening a new transaction.

    `async with joined(uow)() as inner` gives back the same `uow` without re-entering it.
    While inside, `commit()` and `rollback()` are no-ops: whoever opened `uow` (e.g.
    `sb_messaging.inbox.process`) makes the single real commit. To abort, a joined use case
    must raise; the exception propagates and the owner's transaction rolls back. Entering
    raises `RuntimeError` unless `uow` is entered and not yet finished.

    Use cases accept it when they type their factory as
    `Callable[[], AbstractAsyncContextManager[TheirUnitOfWork]]`; a unit of work class is one.
    """
    return uow.joined_view
