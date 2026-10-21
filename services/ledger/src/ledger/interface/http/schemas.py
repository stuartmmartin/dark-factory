"""HTTP transport models, separate from the application DTOs so the API contract stays stable.

Amounts cross the API as `DecimalStr` strings, never JSON numbers (D17).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ledger.application.dto import (
    AccountListResult,
    AccountResult,
    BalanceResult,
    JournalEntryResult,
    JournalLineCommand,
)
from ledger.application.policies.double_entry import MAX_LINES
from ledger.domain.amounts import DecimalStr
from ledger.domain.journal import Side


class AccountIn(BaseModel):
    """Open an account. The use case validates the name and currency (OpenAccount R1)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    currency: str


class AccountOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    currency: str
    opened_at: datetime

    @classmethod
    def of(cls, result: AccountResult) -> AccountOut:
        return cls(
            id=result.id, name=result.name, currency=result.currency, opened_at=result.opened_at
        )


class AccountListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AccountOut]

    @classmethod
    def of(cls, result: AccountListResult) -> AccountListOut:
        return cls(items=[AccountOut.of(a) for a in result.items])


class JournalLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: UUID
    side: Side
    amount: DecimalStr = Field(description="Positive, in the account's currency, e.g. 100.00")

    def command(self) -> JournalLineCommand:
        return JournalLineCommand(account_id=self.account_id, side=self.side, amount=self.amount)


class JournalEntryIn(BaseModel):
    """Post an entry. The use case checks the balance and the accounts (PostJournalEntry R1-R3);
    the line bound is repeated here so an oversized body never reaches it."""

    model_config = ConfigDict(extra="forbid")

    description: str
    lines: list[JournalLineIn] = Field(max_length=MAX_LINES)


class JournalLineOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: UUID
    side: Side
    amount: str


class JournalEntryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    description: str
    currency: str
    posted_at: datetime
    lines: list[JournalLineOut]

    @classmethod
    def of(cls, result: JournalEntryResult) -> JournalEntryOut:
        return cls(
            id=result.id,
            description=result.description,
            currency=result.currency,
            posted_at=result.posted_at,
            lines=[
                JournalLineOut(account_id=line.account_id, side=line.side, amount=line.amount)
                for line in result.lines
            ],
        )


class BalanceOut(BaseModel):
    """Decimal strings in the account's currency. `balance` is debits minus credits."""

    model_config = ConfigDict(extra="forbid")

    account_id: UUID
    currency: str
    debits: str
    credits: str
    balance: str

    @classmethod
    def of(cls, result: BalanceResult) -> BalanceOut:
        return cls.model_validate(result.model_dump())
