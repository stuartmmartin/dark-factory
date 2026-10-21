from datetime import UTC, datetime
from uuid import UUID

import pytest

from ledger.domain.journal import JournalEntry, JournalLine, Side
from sb_kernel.errors import CurrencyMismatch, ValidationFailed
from sb_kernel.money import Currency, Money

POSTED = datetime(2026, 3, 1, 12, tzinfo=UTC)
CASH, EQUITY = UUID(int=1), UUID(int=2)


def lines(currency: str = "USD") -> tuple[JournalLine, ...]:
    return (
        JournalLine(CASH, Side.DEBIT, Money.of("100.00", currency)),
        JournalLine(EQUITY, Side.CREDIT, Money.of("100.00", currency)),
    )


def make(**over: object) -> JournalEntry:
    data: dict[str, object] = {
        "id": UUID(int=10),
        "tenant_id": UUID(int=9),
        "description": "Owner contribution",
        "currency": Currency.of("USD"),
        "posted_at": POSTED,
        "lines": lines(),
    }
    data.update(over)
    return JournalEntry(**data)  # type: ignore[arg-type]


def test_valid_entry() -> None:
    entry = make()
    assert [line.side for line in entry.lines] == [Side.DEBIT, Side.CREDIT]


def test_side_values_are_the_wire_form() -> None:
    assert Side("debit") is Side.DEBIT
    assert Side("credit") is Side.CREDIT


@pytest.mark.parametrize(
    "description", ["", "   ", "x" * 201, 7], ids=["empty", "blank", "201", "not-a-string"]
)
def test_invalid_descriptions_are_rejected(description: object) -> None:
    with pytest.raises(ValidationFailed, match="description"):
        make(description=description)


def test_naive_posted_at_is_rejected() -> None:
    with pytest.raises(ValidationFailed, match="timezone"):
        make(posted_at=datetime(2026, 3, 1, 12))  # noqa: DTZ001 - the invalid input under test


def test_a_line_in_another_currency_is_a_currency_mismatch() -> None:
    with pytest.raises(CurrencyMismatch):
        make(lines=lines("EUR"))
