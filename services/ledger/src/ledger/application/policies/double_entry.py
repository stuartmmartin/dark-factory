"""Double-entry rules: an entry's lines must balance, and a balance is debits minus credits.

Pure (A5): no I/O, no clock. Exposed to humans as the "Journal entry" and "Transfer" SQLAdmin
acceptors.

Rules:
    P1: An entry has 2-100 lines. Every amount is greater than zero and has no more decimal
        places than its currency's minor units: excess precision is rejected, never rounded.
    P2: Total debits equal total credits, or the entry "does not balance".
    P3: An account's balance is its debits minus its credits (debit-positive), so an account
        that is mostly credited has a negative balance.
    P4: A transfer of an amount from one account to another (`ledger-cli transfer`) is a
        two-line entry that debits the "to" account and credits the "from" account, so P1 and
        P2 apply to it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, cast
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, field_validator

from ledger.domain.accounts import MAX_NAME
from ledger.domain.amounts import DecimalStr, to_decimal_str
from ledger.domain.journal import JournalLine, Side, Totals
from sb_kernel.errors import ValidationFailed
from sb_kernel.money import Currency, Money

VERSION = "1"
MIN_LINES = 2
MAX_LINES = 100


def check_line_count(count: int) -> None:
    """P1's bound alone, so a caller can apply it before loading anything per line."""
    if not MIN_LINES <= count <= MAX_LINES:
        raise ValidationFailed(f"an entry needs {MIN_LINES}-{MAX_LINES} lines")


def check_balanced(lines: Sequence[JournalLine], currency: Currency) -> Totals:
    """The entry's totals per side; ValidationFailed unless P1 and P2 hold."""
    check_line_count(len(lines))
    debit_total = credit_total = Money.zero(currency)
    for line in lines:
        if line.amount.amount <= 0:
            raise ValidationFailed("every amount must be positive")
        line.amount.minor_units()  # P1: raises ValidationFailed on excess precision
        if line.side is Side.DEBIT:
            debit_total += line.amount
        else:
            credit_total += line.amount
    if debit_total != credit_total:
        raise ValidationFailed(
            f"entry does not balance: debits {debit_total}, credits {credit_total}"
        )
    return Totals(debit_total, credit_total)


def account_balance(debit_total: Money, credit_total: Money) -> Money:
    """P3: debit-positive."""
    return debit_total - credit_total


class LineInput(BaseModel):
    side: Side
    amount: DecimalStr


def _parse_lines(value: object) -> object:
    """'debit 60.00, credit 60.00' (or the admin form's ['debit 60.00', 'credit 60.00']) →
    [{side, amount}, ...]; anything else is left to pydantic."""
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, list):
        return value
    return [_parse_line(part) for part in cast("list[object]", value)]


def _parse_line(part: object) -> object:
    if isinstance(part, str):
        match part.split():
            case [side, amount]:
                return {"side": side.lower(), "amount": amount}
            case _:
                pass
    return part


class JournalEntryInput(BaseModel):
    currency: str = Field(default="USD", description="ISO 4217 code")
    lines: list[LineInput] = Field(
        max_length=MAX_LINES,
        description="Comma-separated lines, e.g. debit 60.00, debit 40.00, credit 100.00",
    )

    _lines = field_validator("lines", mode="before")(_parse_lines)


class JournalEntryOutput(BaseModel):
    currency: str
    debits: str
    credits: str


def journal_entry_acceptor(inp: JournalEntryInput) -> JournalEntryOutput:
    currency = Currency.of(inp.currency)
    lines = [
        JournalLine(UUID(int=i), line.side, Money.of(line.amount, currency))
        for i, line in enumerate(inp.lines)
    ]
    totals = check_balanced(lines, currency)
    return JournalEntryOutput(
        currency=currency.code,
        debits=to_decimal_str(totals.debits),
        credits=to_decimal_str(totals.credits),
    )


AccountName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_NAME)
]


class TransferInput(BaseModel):
    amount: DecimalStr = Field(
        title="Amount", description="e.g. 5000.00, within the currency's minor units"
    )
    currency: str = Field(default="USD", title="Currency", description="ISO 4217 code")
    from_account: AccountName = Field(
        title="From account", description="Credited, e.g. Owner equity"
    )
    to_account: AccountName = Field(title="To account", description="Debited, e.g. Operating cash")


class TransferOutput(BaseModel):
    currency: str
    debit: str
    credit: str
    debits: str
    credits: str


def transfer_acceptor(inp: TransferInput) -> TransferOutput:
    """P4: the entry `ledger-cli transfer` posts, checked by P1 and P2. Names are labels only."""
    currency = Currency.of(inp.currency)
    amount = Money.of(inp.amount, currency)
    to_id, from_id = UUID(int=0), UUID(int=1)
    totals = check_balanced(
        [JournalLine(to_id, Side.DEBIT, amount), JournalLine(from_id, Side.CREDIT, amount)],
        currency,
    )
    shown = to_decimal_str(amount)
    return TransferOutput(
        currency=currency.code,
        debit=f"{shown} {inp.to_account}",
        credit=f"{shown} {inp.from_account}",
        debits=to_decimal_str(totals.debits),
        credits=to_decimal_str(totals.credits),
    )
