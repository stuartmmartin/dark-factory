"""Ports the ledger's use cases depend on; `ledger.infrastructure` implements them (A1, A6).

Every repository is scoped to the current tenant: RLS does it in SQL, the fakes filter.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import date
from typing import Protocol
from uuid import UUID

from ledger.domain.accounts import Account
from ledger.domain.journal import JournalEntry, Totals
from sb_kernel.uow import UnitOfWork


class AccountRepository(Protocol):
    async def get(self, account_id: UUID) -> Account | None: ...
    async def add(self, account: Account) -> None: ...
    async def oldest_first(self, limit: int) -> list[Account]:
        """The current tenant's accounts by (opened_at, id), at most `limit` of them."""
        ...


class JournalRepository(Protocol):
    async def add(self, entry: JournalEntry) -> None:
        """Insert the entry and its lines. Entries are append-only: never updated or deleted."""
        ...

    async def totals(self, account: Account) -> Totals:
        """Sums of the account's debit and credit lines, in its currency; zero when it has none."""
        ...


class AccountStatsRepository(Protocol):
    """The per-tenant account-count projection and its dated snapshots."""

    async def count(self) -> int:
        """The current tenant's account count; 0 when nothing has been recorded."""
        ...

    async def increment(self) -> int:
        """Add one to the current tenant's count and return the new count."""
        ...

    async def upsert_snapshot(self, as_of: date, accounts: int) -> None: ...
    async def snapshot(self, as_of: date) -> int | None: ...


class LedgerUnitOfWork(UnitOfWork, Protocol):
    accounts: AccountRepository
    journal: JournalRepository
    stats: AccountStatsRepository


UowFactory = Callable[[], AbstractAsyncContextManager[LedgerUnitOfWork]]
"""A new unit of work per call, or `sb_db.uow.joined(uow)` to join an open one (D13)."""
