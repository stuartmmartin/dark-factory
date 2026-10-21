"""The ledger's SQL unit of work: `sb_db`'s tenant-scoped transaction plus its repositories."""

from __future__ import annotations

from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ledger.application.ports import AccountRepository, AccountStatsRepository, JournalRepository
from ledger.infrastructure.repositories import (
    SqlAccountRepository,
    SqlAccountStatsRepository,
    SqlJournalRepository,
)
from sb_db.platform import PlatformTables
from sb_db.uow import SqlAlchemyUnitOfWork
from sb_kernel.clock import Clock
from sb_kernel.context import current_context


class SqlLedgerUnitOfWork(SqlAlchemyUnitOfWork):
    """Single use (D14). The repositories exist only after `__aenter__`, like `session`."""

    accounts: AccountRepository
    journal: JournalRepository
    stats: AccountStatsRepository

    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], tables: PlatformTables, clock: Clock
    ) -> None:
        super().__init__(sessions, tables, clock)
        self._ledger_clock = clock

    async def __aenter__(self) -> Self:
        # Begins the transaction and sets app.tenant_id; raises if re-entered.
        await super().__aenter__()
        self.accounts = SqlAccountRepository(self.session)
        self.journal = SqlJournalRepository(self.session)
        self.stats = SqlAccountStatsRepository(
            self.session, current_context().tenant_id, self._ledger_clock
        )
        return self
