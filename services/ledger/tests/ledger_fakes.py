"""In-memory fakes of the ledger ports (T3). Writes are staged and applied only on commit, so
use case tests see real transactional behaviour (nothing persists when a rule fails).

The lifecycle mirrors `sb_db.uow.SqlAlchemyUnitOfWork` (D14): single use, commit after finishing
raises, rollback after commit is a no-op, buffers refuse work once finished, and `fake_joined`
stands in for `sb_db.uow.joined` (which is typed for SqlAlchemyUnitOfWork only)."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from datetime import date
from types import TracebackType
from typing import Any, Self, cast
from uuid import UUID

from ledger.application.ports import (
    AccountRepository,
    AccountStatsRepository,
    JournalRepository,
    UowFactory,
)
from ledger.domain.accounts import Account
from ledger.domain.journal import JournalEntry, Side, Totals
from sb_db.audit import canonical_json
from sb_kernel.context import current_context
from sb_kernel.errors import Conflict, IdempotencyKeyReused
from sb_kernel.events import DomainEvent
from sb_kernel.money import Money
from sb_kernel.uow import AuditLog, IdempotencyStore, Outbox, StoredResponse

FINISHED = "unit of work already finished"  # same text as sb_db.lifecycle.FINISHED


@dataclass
class AuditRecord:
    tenant_id: UUID
    action: str
    entity_type: str
    entity_id: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    reason: str | None


def _as_stored(payload: Mapping[str, object] | None) -> dict[str, Any] | None:
    """What SqlAuditLog stores: a canonical JSON copy (floats and naive datetimes raise)."""
    if payload is None:
        return None
    return cast(dict[str, Any], json.loads(canonical_json(payload)))


@dataclass
class LedgerState:
    """Committed state shared by every FakeLedgerUoW created by one factory."""

    accounts: dict[UUID, Account] = field(default_factory=dict)
    entries: dict[UUID, JournalEntry] = field(default_factory=dict)
    counts: dict[UUID, int] = field(default_factory=dict)
    snapshots: dict[tuple[UUID, date], int] = field(default_factory=dict)
    audit: list[AuditRecord] = field(default_factory=list)
    events: list[DomainEvent] = field(default_factory=list)
    idempotency: dict[tuple[UUID, str], StoredResponse] = field(default_factory=dict)
    commits: int = 0
    # Test hook for R3's race: `idempotency.get` returns None (as if the other request had not
    # committed yet) while `save` still sees the committed row.
    hide_idempotency_reads: bool = False


class FakeAccounts:
    def __init__(self, uow: FakeLedgerUoW) -> None:
        self._uow = uow

    async def get(self, account_id: UUID) -> Account | None:
        account = self._uow.staged_accounts.get(account_id) or self._uow.state.accounts.get(
            account_id
        )
        return account if account is not None and account.tenant_id == self._uow.tenant_id else None

    async def add(self, account: Account) -> None:
        self._uow.check_active()
        if account.id in self._uow.staged_accounts or account.id in self._uow.state.accounts:
            raise Conflict(f"account {account.id} already exists")  # primary-key violation
        self._uow.staged_accounts[account.id] = account

    async def oldest_first(self, limit: int) -> list[Account]:
        visible = {**self._uow.state.accounts, **self._uow.staged_accounts}.values()
        mine = [a for a in visible if a.tenant_id == self._uow.tenant_id]
        return sorted(mine, key=lambda a: (a.opened_at, a.id))[:limit]


class FakeJournal:
    def __init__(self, uow: FakeLedgerUoW) -> None:
        self._uow = uow

    async def add(self, entry: JournalEntry) -> None:
        self._uow.check_active()
        if entry.id in self._uow.staged_entries or entry.id in self._uow.state.entries:
            raise Conflict(f"journal entry {entry.id} already exists")
        self._uow.staged_entries[entry.id] = entry

    async def totals(self, account: Account) -> Totals:
        debits = credits_ = Money.zero(account.currency)
        for entry in {**self._uow.state.entries, **self._uow.staged_entries}.values():
            if entry.tenant_id != self._uow.tenant_id:
                continue
            for line in entry.lines:
                if line.account_id != account.id:
                    continue
                if line.side is Side.DEBIT:
                    debits += line.amount
                else:
                    credits_ += line.amount
        return Totals(debits, credits_)


class FakeStats:
    def __init__(self, uow: FakeLedgerUoW) -> None:
        self._uow = uow

    async def count(self) -> int:
        tenant = self._uow.tenant_id
        return self._uow.staged_counts.get(tenant, self._uow.state.counts.get(tenant, 0))

    async def increment(self) -> int:
        self._uow.check_active()
        new = await self.count() + 1
        self._uow.staged_counts[self._uow.tenant_id] = new
        return new

    async def upsert_snapshot(self, as_of: date, accounts: int) -> None:
        self._uow.check_active()
        self._uow.staged_snapshots[(self._uow.tenant_id, as_of)] = accounts

    async def snapshot(self, as_of: date) -> int | None:
        key = (self._uow.tenant_id, as_of)
        return self._uow.staged_snapshots.get(key, self._uow.state.snapshots.get(key))


class FakeAudit:
    def __init__(self, uow: FakeLedgerUoW) -> None:
        self._uow = uow

    def record(
        self,
        *,
        action: str,
        entity_type: str,
        entity_id: str,
        before: Mapping[str, object] | None,
        after: Mapping[str, object] | None,
        reason: str | None = None,
    ) -> None:
        self._uow.check_active()
        self._uow.staged_audit.append(
            AuditRecord(
                self._uow.tenant_id,
                action,
                entity_type,
                entity_id,
                _as_stored(before),
                _as_stored(after),
                reason,
            )
        )


class FakeOutbox:
    def __init__(self, uow: FakeLedgerUoW) -> None:
        self._uow = uow

    def add(self, event: DomainEvent) -> None:
        self._uow.check_active()
        self._uow.staged_events.append(event)


class FakeIdempotency:
    """Same contract as sb_db.idempotency.SqlIdempotencyStore (D14, D15)."""

    def __init__(self, uow: FakeLedgerUoW) -> None:
        self._uow = uow

    def _existing(self, key: str) -> StoredResponse | None:
        k = (self._uow.tenant_id, key)
        return self._uow.staged_idempotency.get(k) or self._uow.state.idempotency.get(k)

    async def get(self, key: str) -> StoredResponse | None:
        if self._uow.state.hide_idempotency_reads:
            return None
        return self._existing(key)

    async def save(self, key: str, request_hash: str, response: Mapping[str, object]) -> None:
        self._uow.check_active()
        existing = self._existing(key)
        if existing is not None:
            if existing.request_hash != request_hash:
                raise IdempotencyKeyReused("idempotency key already used for a different request")
            raise Conflict("idempotency key already in use")
        stored = json.loads(json.dumps(response))  # JSONB: non-JSON values raise TypeError
        self._uow.staged_idempotency[(self._uow.tenant_id, key)] = StoredResponse(
            request_hash, stored
        )


class FakeLedgerUoW:
    # Typed as the ports, so pyright checks the fakes conform (see `fake_factory`).
    accounts: AccountRepository
    journal: JournalRepository
    stats: AccountStatsRepository
    audit: AuditLog
    outbox: Outbox
    idempotency: IdempotencyStore

    def __init__(self, state: LedgerState) -> None:
        self.state = state
        self._entered = self._finished = self._commit_called = False
        self._joined = 0  # open fake_joined views: commit/rollback are no-ops while > 0
        self.accounts, self.stats = FakeAccounts(self), FakeStats(self)
        self.journal = FakeJournal(self)
        self.audit, self.outbox = FakeAudit(self), FakeOutbox(self)
        self.idempotency = FakeIdempotency(self)

    @property
    def active(self) -> bool:
        return self._entered and not self._finished

    def check_active(self) -> None:
        if not self.active:
            raise RuntimeError(FINISHED if self._finished else "unit of work not entered")

    @asynccontextmanager
    async def joined_view(self) -> AsyncGenerator[Self]:
        if not self.active:
            raise RuntimeError("joined view: the outer unit of work is not active")
        self._joined += 1
        try:
            yield self  # an exception propagates, so the owner rolls back
        finally:
            self._joined -= 1

    async def __aenter__(self) -> Self:
        if self._entered:
            raise RuntimeError("unit of work already entered; create a new one per use case")
        self.tenant_id = current_context().tenant_id  # raises Forbidden, like the SQL UoW
        self._entered = True
        self.staged_accounts: dict[UUID, Account] = {}
        self.staged_entries: dict[UUID, JournalEntry] = {}
        self.staged_counts: dict[UUID, int] = {}
        self.staged_snapshots: dict[tuple[UUID, date], int] = {}
        self.staged_audit: list[AuditRecord] = []
        self.staged_events: list[DomainEvent] = []
        self.staged_idempotency: dict[tuple[UUID, str], StoredResponse] = {}
        return self

    async def commit(self) -> None:
        if self._joined:  # the owner of the transaction makes the one commit
            return
        if self._finished:
            raise RuntimeError(FINISHED)
        self._finished = self._commit_called = True
        self.state.accounts.update(self.staged_accounts)
        self.state.entries.update(self.staged_entries)
        self.state.counts.update(self.staged_counts)
        self.state.snapshots.update(self.staged_snapshots)
        self.state.audit.extend(self.staged_audit)
        self.state.events.extend(self.staged_events)
        self.state.idempotency.update(self.staged_idempotency)
        self.state.commits += 1

    async def rollback(self) -> None:
        if self._joined or self._commit_called:  # no-op when joined, and after a commit
            return
        if self._finished:
            raise RuntimeError(FINISHED)
        self._finished = True

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._finished = True  # uncommitted staged writes are simply dropped


def fake_factory(state: LedgerState) -> UowFactory:
    """A `UowFactory` of single-use fakes sharing `state` (typed, so pyright checks conformance)."""
    return lambda: FakeLedgerUoW(state)


def fake_joined(uow: FakeLedgerUoW) -> Callable[[], AbstractAsyncContextManager[FakeLedgerUoW]]:
    """The fake counterpart of `sb_db.uow.joined`: a factory that joins the open `uow`."""
    return uow.joined_view
