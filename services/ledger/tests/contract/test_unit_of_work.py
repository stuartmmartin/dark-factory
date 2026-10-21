"""Unit-of-work lifecycle contract (D14): fake and SQL behave the same."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import pytest

from ledger.application.ports import LedgerUnitOfWork, UowFactory
from ledger.domain.accounts import Account

Join = Callable[[LedgerUnitOfWork], Callable[[], AbstractAsyncContextManager[LedgerUnitOfWork]]]


class BoomError(Exception):
    pass


async def _visible(uow_factory: UowFactory, account: Account) -> bool:
    async with uow_factory() as uow:
        return await uow.accounts.get(account.id) is not None


async def test_entering_twice_raises(uow_factory: UowFactory) -> None:
    uow = uow_factory()
    async with uow:
        with pytest.raises(RuntimeError):
            await uow.__aenter__()


async def test_commit_after_commit_raises(uow_factory: UowFactory) -> None:
    async with uow_factory() as uow:
        await uow.commit()
        with pytest.raises(RuntimeError):
            await uow.commit()


async def test_rollback_after_commit_is_a_no_op(
    uow_factory: UowFactory, new_account: Callable[[], Account]
) -> None:
    account = new_account()
    async with uow_factory() as uow:
        await uow.accounts.add(account)
        await uow.commit()
        await uow.rollback()
    assert await _visible(uow_factory, account)


async def test_writes_without_commit_are_not_visible(
    uow_factory: UowFactory, new_account: Callable[[], Account]
) -> None:
    account = new_account()
    async with uow_factory() as uow:
        await uow.accounts.add(account)
        await uow.stats.increment()
    assert not await _visible(uow_factory, account)
    async with uow_factory() as uow:
        assert await uow.stats.count() == 0


async def test_joined_commit_is_a_no_op_and_only_the_owner_commits(
    uow_factory: UowFactory, new_account: Callable[[], Account], join: Join
) -> None:
    account = new_account()
    async with uow_factory() as owner:
        async with join(owner)() as inner:
            assert inner is owner
            await inner.accounts.add(account)
            await inner.commit()  # no-op: the owner decides
        assert not await _visible(uow_factory, account)
        await owner.commit()
    assert await _visible(uow_factory, account)


async def test_an_exception_inside_the_joined_view_persists_nothing(
    uow_factory: UowFactory, new_account: Callable[[], Account], join: Join
) -> None:
    account = new_account()

    async def handler_fails_after_writing() -> None:
        async with uow_factory() as owner, join(owner)() as inner:
            await inner.accounts.add(account)
            await inner.stats.increment()
            await inner.commit()  # a no-op: raising is how a joined use case aborts
            raise BoomError

    with pytest.raises(BoomError):
        await handler_fails_after_writing()
    assert not await _visible(uow_factory, account)
    async with uow_factory() as uow:
        assert await uow.stats.count() == 0
