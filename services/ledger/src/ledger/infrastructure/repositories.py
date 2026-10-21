"""SQL implementations of the ledger ports. RLS scopes every read to the session's tenant (A13).

Writes that name a tenant (`account_counts`, `account_count_snapshots`) pass it explicitly; RLS
`WITH CHECK` rejects a row whose `tenant_id` is not the session's. The stats reads also filter by
the unit of work's tenant explicitly, on top of RLS (defence in depth).
"""

from __future__ import annotations

from datetime import date
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Row, Table, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ledger.domain.accounts import Account
from ledger.domain.journal import JournalEntry, Side, Totals
from ledger.infrastructure.models import (
    AccountCountRow,
    AccountCountSnapshotRow,
    AccountRow,
    JournalEntryRow,
    JournalLineRow,
)
from sb_kernel.clock import Clock
from sb_kernel.errors import Conflict
from sb_kernel.money import Currency, Money

# Core tables of the mapped classes (declarative `__table__` is typed as a FromClause).
_accounts = cast(Table, AccountRow.__table__)
_counts = cast(Table, AccountCountRow.__table__)
_snapshots = cast(Table, AccountCountSnapshotRow.__table__)
_entries = cast(Table, JournalEntryRow.__table__)
_lines = cast(Table, JournalLineRow.__table__)


def _account(row: Row[Any]) -> Account:
    return Account(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        currency=Currency.of(row.currency),
        opened_at=row.opened_at,
    )


class SqlAccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, account_id: UUID) -> Account | None:
        row = (
            await self._session.execute(select(_accounts).where(_accounts.c.id == account_id))
        ).first()
        return None if row is None else _account(row)

    async def oldest_first(self, limit: int) -> list[Account]:
        query = select(_accounts).order_by(_accounts.c.opened_at, _accounts.c.id).limit(limit)
        return [_account(row) for row in await self._session.execute(query)]

    async def add(self, account: Account) -> None:
        # ON CONFLICT DO NOTHING rather than catching the IntegrityError: a failed statement
        # would abort the whole transaction, while the fake's Conflict leaves it usable.
        inserted = await self._session.execute(
            insert(_accounts)
            .values(
                id=account.id,
                tenant_id=account.tenant_id,
                name=account.name,
                currency=account.currency.code,
                opened_at=account.opened_at,
            )
            .on_conflict_do_nothing(index_elements=[_accounts.c.id])
            .returning(_accounts.c.id)
        )
        if inserted.first() is None:
            raise Conflict(f"account {account.id} already exists")


class SqlJournalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, entry: JournalEntry) -> None:
        # A duplicate id fails the primary key; ids are server-generated, so that is a bug.
        await self._session.execute(
            insert(_entries).values(
                id=entry.id,
                tenant_id=entry.tenant_id,
                description=entry.description,
                currency=entry.currency.code,
                posted_at=entry.posted_at,
            )
        )
        await self._session.execute(
            insert(_lines),
            [
                {
                    "entry_id": entry.id,
                    "line_no": line_no,
                    "tenant_id": entry.tenant_id,
                    "account_id": line.account_id,
                    "side": line.side.value,
                    "amount": line.amount.amount,
                }
                for line_no, line in enumerate(entry.lines, start=1)
            ],
        )

    async def totals(self, account: Account) -> Totals:
        # One indexed aggregate (ix_journal_lines_account_id); RLS scopes it to the tenant.
        query = (
            select(_lines.c.side, func.sum(_lines.c.amount))
            .where(_lines.c.account_id == account.id)
            .group_by(_lines.c.side)
        )
        sums = {Side(side): total for side, total in await self._session.execute(query)}
        return Totals(
            debits=Money.of(sums.get(Side.DEBIT, 0), account.currency),
            credits=Money.of(sums.get(Side.CREDIT, 0), account.currency),
        )


class SqlAccountStatsRepository:
    def __init__(self, session: AsyncSession, tenant_id: UUID, clock: Clock) -> None:
        self._session, self._tenant_id, self._clock = session, tenant_id, clock

    async def count(self) -> int:
        # RLS scopes this already; the explicit tenant filter is defence in depth.
        query = select(_counts.c.accounts).where(_counts.c.tenant_id == self._tenant_id)
        accounts = (await self._session.execute(query)).scalar_one_or_none()
        return 0 if accounts is None else int(accounts)

    async def increment(self) -> int:
        # One atomic upsert: concurrent consumers of one tenant serialize on the row lock.
        statement = insert(_counts).values(
            tenant_id=self._tenant_id, accounts=1, updated_at=self._clock.now()
        )
        statement = statement.on_conflict_do_update(
            index_elements=[_counts.c.tenant_id],
            set_={
                "accounts": _counts.c.accounts + 1,
                "updated_at": statement.excluded.updated_at,
            },
        ).returning(_counts.c.accounts)
        return int((await self._session.execute(statement)).scalar_one())

    async def upsert_snapshot(self, as_of: date, accounts: int) -> None:
        statement = insert(_snapshots).values(
            tenant_id=self._tenant_id, as_of=as_of, accounts=accounts
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[_snapshots.c.tenant_id, _snapshots.c.as_of],
                set_={"accounts": statement.excluded.accounts},
            )
        )

    async def snapshot(self, as_of: date) -> int | None:
        accounts = (
            await self._session.execute(
                # RLS scopes this already; the explicit tenant filter is defence in depth.
                select(_snapshots.c.accounts).where(
                    _snapshots.c.tenant_id == self._tenant_id, _snapshots.c.as_of == as_of
                )
            )
        ).scalar_one_or_none()
        return None if accounts is None else int(accounts)
