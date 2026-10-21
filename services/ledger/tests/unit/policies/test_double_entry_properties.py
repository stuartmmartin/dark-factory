from decimal import Decimal
from uuid import UUID

from hypothesis import given
from hypothesis import strategies as st

from ledger.application.policies.double_entry import account_balance, check_balanced
from ledger.domain.journal import JournalLine, Side
from sb_kernel.money import Currency, Money

USD = Currency.of("USD")
amounts = st.integers(min_value=1, max_value=10**12).map(
    lambda cents: Money.of(Decimal(cents).scaleb(-2), USD)
)


@given(st.lists(amounts, min_size=1, max_size=49))
def test_debits_mirrored_by_one_credit_always_balance(debits: list[Money]) -> None:
    total = sum(debits, Money.zero(USD))
    lines = [JournalLine(UUID(int=i + 1), Side.DEBIT, d) for i, d in enumerate(debits)]
    lines.append(JournalLine(UUID(int=0), Side.CREDIT, total))
    totals = check_balanced(lines, USD)
    assert totals.debits == totals.credits == total
    assert account_balance(totals.debits, totals.credits).is_zero()


@given(amounts, amounts)
def test_balance_is_antisymmetric(debit_total: Money, credit_total: Money) -> None:
    assert account_balance(debit_total, credit_total) == -account_balance(credit_total, debit_total)
