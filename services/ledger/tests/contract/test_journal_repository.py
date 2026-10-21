"""JournalRepository and account listing contract: fake and SQL behave the same."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ledger.application.ports import UowFactory
from ledger.domain.accounts import Account
from ledger.domain.journal import JournalEntry, JournalLine, Side, Totals
from sb_kernel.context import RequestContext, current_context
from sb_kernel.money import Currency, Money

USD = Currency.of("USD")
POSTED = datetime(2026, 3, 2, 9, tzinfo=UTC)


def _entry(debit: Account, credit: Account, amount: str) -> JournalEntry:
    money = Money.of(amount, USD)
    return JournalEntry(
        id=uuid4(),
        tenant_id=current_context().tenant_id,
        description="Transfer",
        currency=USD,
        posted_at=POSTED,
        lines=(
            JournalLine(debit.id, Side.DEBIT, money),
            JournalLine(credit.id, Side.CREDIT, money),
        ),
    )


async def _open(uow_factory: UowFactory, *accounts: Account) -> None:
    async with uow_factory() as uow:
        for account in accounts:
            await uow.accounts.add(account)
        await uow.commit()


async def test_totals_sum_each_side_across_entries(
    uow_factory: UowFactory, new_account: Callable[[], Account]
) -> None:
    cash, equity = new_account(), new_account()
    await _open(uow_factory, cash, equity)
    async with uow_factory() as uow:
        await uow.journal.add(_entry(cash, equity, "100.00"))
        await uow.journal.add(_entry(equity, cash, "30.25"))
        await uow.commit()
    async with uow_factory() as uow:
        assert await uow.journal.totals(cash) == Totals(
            Money.of("100.00", USD), Money.of("30.25", USD)
        )
        assert await uow.journal.totals(equity) == Totals(
            Money.of("30.25", USD), Money.of("100.00", USD)
        )


async def test_an_account_without_lines_has_zero_totals(
    uow_factory: UowFactory, new_account: Callable[[], Account]
) -> None:
    account = new_account()
    await _open(uow_factory, account)
    async with uow_factory() as uow:
        assert await uow.journal.totals(account) == Totals(Money.zero(USD), Money.zero(USD))


async def test_entries_without_commit_are_not_counted(
    uow_factory: UowFactory, new_account: Callable[[], Account]
) -> None:
    cash, equity = new_account(), new_account()
    await _open(uow_factory, cash, equity)
    async with uow_factory() as uow:
        await uow.journal.add(_entry(cash, equity, "5.00"))
    async with uow_factory() as uow:
        assert (await uow.journal.totals(cash)).debits.is_zero()


async def test_another_tenant_sees_no_lines(
    uow_factory: UowFactory,
    new_account: Callable[[], Account],
    other_tenant: Callable[[], AbstractContextManager[RequestContext]],
) -> None:
    cash, equity = new_account(), new_account()
    await _open(uow_factory, cash, equity)
    async with uow_factory() as uow:
        await uow.journal.add(_entry(cash, equity, "5.00"))
        await uow.commit()
    with other_tenant():
        async with uow_factory() as uow:
            assert (await uow.journal.totals(cash)).debits.is_zero()


async def test_listing_returns_the_tenants_accounts_oldest_first(
    uow_factory: UowFactory,
    new_account: Callable[[], Account],
    other_tenant: Callable[[], AbstractContextManager[RequestContext]],
) -> None:
    first = new_account()
    second = Account(
        id=uuid4(),
        tenant_id=first.tenant_id,
        name="Savings",
        currency=USD,
        opened_at=first.opened_at + timedelta(hours=1),
    )
    await _open(uow_factory, second, first)
    with other_tenant():
        await _open(uow_factory, new_account())
    async with uow_factory() as uow:
        assert await uow.accounts.oldest_first(limit=10) == [first, second]
        assert await uow.accounts.oldest_first(limit=1) == [first]
