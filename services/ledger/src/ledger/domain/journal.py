"""Journal entries: the double-entry record of money moving between accounts.

The entity holds its structural invariants only. Whether the lines balance, and how many there
may be, is the `double_entry` policy's job (A3).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sb_kernel.errors import CurrencyMismatch, ValidationFailed
from sb_kernel.money import Currency, Money

MAX_DESCRIPTION = 200


class Side(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


@dataclass(frozen=True, slots=True)
class JournalLine:
    account_id: UUID
    side: Side
    amount: Money


@dataclass(frozen=True, slots=True)
class Totals:
    """Debit and credit sums in one currency: of an entry, or of an account's lines."""

    debits: Money
    credits: Money


@dataclass(frozen=True, slots=True)
class JournalEntry:
    """Immutable once posted: a correction is a new, reversing entry."""

    id: UUID
    tenant_id: UUID
    description: str
    currency: Currency
    posted_at: datetime
    lines: tuple[JournalLine, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.description, str):  # pyright: ignore[reportUnnecessaryIsInstance]  # runtime guard
            raise ValidationFailed("description must be a string")
        if not self.description.strip() or len(self.description) > MAX_DESCRIPTION:
            raise ValidationFailed(f"description must be 1-{MAX_DESCRIPTION} characters")
        if self.posted_at.tzinfo is None or self.posted_at.utcoffset() is None:
            raise ValidationFailed("posted_at must be timezone-aware")
        for line in self.lines:
            if line.amount.currency != self.currency:
                raise CurrencyMismatch(f"{line.amount.currency.code} vs {self.currency.code}")
