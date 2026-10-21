"""GetAccountBalance's rules: one `test_R<n>_*` per `R<n>` line of its docstring (T2)."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from ledger.application.dto import GetAccountBalanceQuery
from ledger.application.use_cases.get_account_balance import GetAccountBalance
from ledger.domain.accounts import Account
from ledger.domain.journal import JournalEntry, JournalLine, Side
from sb_kernel.context import current_context
from sb_kernel.errors import NotFound
from sb_kernel.money import Currency, Money

AT = datetime(2026, 3, 1, 12, tzinfo=UTC)
USD = Currency.of("USD")
CASH, EQUITY, ELSEWHERE = UUID(int=1), UUID(int=2), UUID(int=3)


def _account(account_id: UUID, tenant: UUID) -> Account:
    return Account(id=account_id, tenant_id=tenant, name="A", currency=USD, opened_at=AT)


def _entry(entry_id: int, debit: UUID, credit: UUID, amount: str) -> JournalEntry:
    money = Money.of(amount, USD)
    return JournalEntry(
        id=UUID(int=entry_id),
        tenant_id=current_context().tenant_id,
        description="Transfer",
        currency=USD,
        posted_at=AT,
        lines=(JournalLine(debit, Side.DEBIT, money), JournalLine(credit, Side.CREDIT, money)),
    )


@pytest.fixture(autouse=True)
def accounts(state) -> None:
    tenant = current_context().tenant_id
    state.accounts[CASH] = _account(CASH, tenant)
    state.accounts[EQUITY] = _account(EQUITY, tenant)
    state.accounts[ELSEWHERE] = _account(ELSEWHERE, UUID(int=0xBEEF))


async def test_R1_balance_is_debits_minus_credits_in_the_accounts_currency(uow, state) -> None:
    state.entries[UUID(int=10)] = _entry(10, CASH, EQUITY, "100.00")
    state.entries[UUID(int=11)] = _entry(11, EQUITY, CASH, "30.25")
    cash = await GetAccountBalance(uow)(GetAccountBalanceQuery(account_id=CASH))
    assert cash.model_dump(exclude={"account_id"}) == {
        "currency": "USD",
        "debits": "100.00",
        "credits": "30.25",
        "balance": "69.75",
    }
    equity = await GetAccountBalance(uow)(GetAccountBalanceQuery(account_id=EQUITY))
    assert equity.balance == "-69.75"


async def test_R1_an_account_without_lines_is_all_zero(uow) -> None:
    result = await GetAccountBalance(uow)(GetAccountBalanceQuery(account_id=CASH))
    assert (result.account_id, result.debits, result.credits, result.balance) == (
        CASH,
        "0.00",
        "0.00",
        "0.00",
    )


@pytest.mark.parametrize("missing", [UUID(int=0xDEAD), ELSEWHERE], ids=["unknown", "other-tenant"])
async def test_R2_an_account_outside_the_tenant_is_not_found(uow, missing) -> None:
    with pytest.raises(NotFound):
        await GetAccountBalance(uow)(GetAccountBalanceQuery(account_id=missing))
