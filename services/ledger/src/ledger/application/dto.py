"""Commands, queries and results of the ledger's use cases (frozen, transport-neutral)."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from ledger.domain.accounts import Account
from ledger.domain.journal import Side


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class OpenAccountCommand(_Frozen):
    name: str
    currency: str
    idempotency_key: str | None = None


class AccountResult(_Frozen):
    id: UUID
    name: str
    currency: str
    opened_at: datetime
    replayed: bool = False


def to_result(account: Account) -> AccountResult:
    return AccountResult(
        id=account.id,
        name=account.name,
        currency=account.currency.code,
        opened_at=account.opened_at,
    )


class GetAccountQuery(_Frozen):
    account_id: UUID


class ListAccountsQuery(_Frozen):
    limit: int = 100


class AccountListResult(_Frozen):
    items: tuple[AccountResult, ...]


class JournalLineCommand(_Frozen):
    account_id: UUID
    side: Side
    amount: str
    """A decimal string in the account's currency (the HTTP layer checks it is a DecimalStr)."""


class PostJournalEntryCommand(_Frozen):
    description: str
    lines: tuple[JournalLineCommand, ...]
    idempotency_key: str | None = None


class JournalLineResult(_Frozen):
    account_id: UUID
    side: Side
    amount: str


class JournalEntryResult(_Frozen):
    id: UUID
    description: str
    currency: str
    posted_at: datetime
    lines: tuple[JournalLineResult, ...]
    replayed: bool = False


class GetAccountBalanceQuery(_Frozen):
    account_id: UUID


class BalanceResult(_Frozen):
    """Amounts are decimal strings in the account's currency; balance = debits - credits."""

    account_id: UUID
    currency: str
    debits: str
    credits: str
    balance: str


class RecordAccountOpenedCommand(_Frozen):
    account_id: UUID


class AccountCountResult(_Frozen):
    accounts: int


class SnapshotAccountCountCommand(_Frozen):
    as_of: date
    idempotency_key: str | None = None


class SnapshotResult(_Frozen):
    as_of: date
    accounts: int
    replayed: bool = False


def request_hash(command: BaseModel) -> str:
    """SHA-256 of the command without its idempotency key (D15).

    Lives here, not in `sb_http`, because `application` never imports the HTTP layer.

    Idempotency keys share one namespace per tenant across every use case (the store is keyed
    by tenant and key only). The command's JSON includes its type-specific fields, so reusing
    a key across use cases hashes differently and raises IdempotencyKeyReused, never replays
    the other use case's response.
    """
    body = command.model_dump_json(exclude={"idempotency_key"})
    return hashlib.sha256(body.encode()).hexdigest()
