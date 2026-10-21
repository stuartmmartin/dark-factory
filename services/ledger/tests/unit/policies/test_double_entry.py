from uuid import UUID

import pytest
from pydantic import ValidationError

from ledger.application.policies.double_entry import (
    MAX_LINES,
    JournalEntryInput,
    TransferInput,
    account_balance,
    check_balanced,
    journal_entry_acceptor,
    transfer_acceptor,
)
from ledger.domain.journal import JournalLine, Side
from sb_kernel.errors import ValidationFailed
from sb_kernel.money import Currency, Money

USD = Currency.of("USD")
A, B, C = UUID(int=1), UUID(int=2), UUID(int=3)


def line(side: Side, amount: str, account: UUID = A, currency: str = "USD") -> JournalLine:
    return JournalLine(account, side, Money.of(amount, currency))


def test_P1_a_balanced_two_line_entry_returns_its_totals() -> None:
    totals = check_balanced([line(Side.DEBIT, "100.00"), line(Side.CREDIT, "100.00", B)], USD)
    assert totals.debits == Money.of("100.00", "USD")
    assert totals.credits == Money.of("100.00", "USD")


def test_P1_a_split_entry_balances_across_many_lines() -> None:
    totals = check_balanced(
        [line(Side.DEBIT, "60.00"), line(Side.DEBIT, "40.00", B), line(Side.CREDIT, "100", C)],
        USD,
    )
    assert totals.debits == totals.credits == Money.of("100.00", "USD")


@pytest.mark.parametrize("count", [0, 1, MAX_LINES + 1], ids=["none", "one", "too-many"])
def test_P1_an_entry_needs_2_to_100_lines(count: int) -> None:
    lines = [line(Side.DEBIT if i % 2 else Side.CREDIT, "1.00") for i in range(count)]
    with pytest.raises(ValidationFailed, match="lines"):
        check_balanced(lines, USD)


def test_P1_exactly_100_lines_is_allowed() -> None:
    lines = [line(Side.DEBIT if i % 2 else Side.CREDIT, "1.00") for i in range(MAX_LINES)]
    assert check_balanced(lines, USD).debits == Money.of(50, "USD")


@pytest.mark.parametrize("amount", ["0", "0.00", "-5.00"], ids=["zero", "zero-cents", "negative"])
def test_P1_every_amount_must_be_positive(amount: str) -> None:
    with pytest.raises(ValidationFailed, match="positive"):
        check_balanced([line(Side.DEBIT, amount), line(Side.CREDIT, amount, B)], USD)


def test_P1_excess_precision_is_rejected_never_rounded() -> None:
    with pytest.raises(ValidationFailed, match="precision"):
        check_balanced([line(Side.DEBIT, "10.005"), line(Side.CREDIT, "10.005", B)], USD)


def test_P1_jpy_allows_no_decimal_places() -> None:
    jpy = Currency.of("JPY")
    with pytest.raises(ValidationFailed, match="precision"):
        check_balanced(
            [line(Side.DEBIT, "1.5", currency="JPY"), line(Side.CREDIT, "1.5", B, "JPY")], jpy
        )


def test_P2_an_unbalanced_entry_is_rejected() -> None:
    with pytest.raises(ValidationFailed, match="does not balance"):
        check_balanced([line(Side.DEBIT, "100.00"), line(Side.CREDIT, "99.99", B)], USD)


def test_P2_two_debits_and_no_credit_does_not_balance() -> None:
    with pytest.raises(ValidationFailed, match="does not balance"):
        check_balanced([line(Side.DEBIT, "1.00"), line(Side.DEBIT, "1.00", B)], USD)


def test_P3_balance_is_debits_minus_credits() -> None:
    assert account_balance(Money.of("150.00", "USD"), Money.of("40.00", "USD")) == Money.of(
        "110.00", "USD"
    )


def test_P3_a_credit_heavy_account_has_a_negative_balance() -> None:
    assert account_balance(Money.of("0", "USD"), Money.of("25.00", "USD")) == Money.of(
        "-25.00", "USD"
    )


def test_acceptor_reports_the_totals_of_a_balanced_entry() -> None:
    out = journal_entry_acceptor(
        JournalEntryInput.model_validate(
            {"currency": "usd", "lines": "debit 60.00, debit 40, credit 100.00"}
        )
    )
    assert out.model_dump() == {"currency": "USD", "debits": "100.00", "credits": "100.00"}


def test_acceptor_accepts_lines_already_split_by_the_admin_form() -> None:
    inp = JournalEntryInput.model_validate({"lines": ["debit 5.00", "credit 5.00"]})
    assert journal_entry_acceptor(inp).debits == "5.00"


def test_acceptor_accepts_typed_lines() -> None:
    inp = JournalEntryInput.model_validate(
        {"lines": [{"side": "debit", "amount": "2.50"}, {"side": "credit", "amount": "2.50"}]}
    )
    assert journal_entry_acceptor(inp).credits == "2.50"


def test_acceptor_rejects_lines_that_are_not_text_or_a_list() -> None:
    with pytest.raises(ValidationError):
        JournalEntryInput.model_validate({"lines": 42})


def test_acceptor_rejects_an_unbalanced_entry() -> None:
    inp = JournalEntryInput.model_validate({"lines": "debit 10.00, credit 9.00"})
    with pytest.raises(ValidationFailed, match="does not balance"):
        journal_entry_acceptor(inp)


@pytest.mark.parametrize(
    "lines", ["debit", "loan 10.00, credit 10.00", "debit ten, credit 10"], ids=str
)
def test_acceptor_rejects_malformed_lines(lines: str) -> None:
    with pytest.raises(ValidationError):
        JournalEntryInput.model_validate({"lines": lines})


def transfer(amount: str, currency: str = "USD") -> TransferInput:
    return TransferInput.model_validate(
        {
            "amount": amount,
            "currency": currency,
            "from_account": "Owner equity",
            "to_account": "Operating cash",
        }
    )


def test_P4_a_transfer_debits_the_to_account_and_credits_the_from_account() -> None:
    out = transfer_acceptor(transfer("5000"))
    assert out.model_dump() == {
        "currency": "USD",
        "debit": "5000.00 Operating cash",
        "credit": "5000.00 Owner equity",
        "debits": "5000.00",
        "credits": "5000.00",
    }


@pytest.mark.parametrize("amount", ["0", "-5.00"], ids=["zero", "negative"])
def test_P4_a_transfer_amount_must_be_positive(amount: str) -> None:
    with pytest.raises(ValidationFailed, match="positive"):
        transfer_acceptor(transfer(amount))


def test_P4_a_transfer_rejects_excess_precision_never_rounds() -> None:
    with pytest.raises(ValidationFailed, match="precision"):
        transfer_acceptor(transfer("10.005"))


def test_P4_a_transfer_needs_both_account_names() -> None:
    with pytest.raises(ValidationError):
        TransferInput.model_validate({"amount": "1.00", "from_account": " ", "to_account": "B"})
