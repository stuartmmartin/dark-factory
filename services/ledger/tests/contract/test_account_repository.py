"""AccountRepository contract: fake and SQL behave the same."""

from collections.abc import Callable
from contextlib import AbstractContextManager

import pytest

from ledger.application.ports import UowFactory
from ledger.domain.accounts import Account
from sb_kernel.context import RequestContext
from sb_kernel.errors import Conflict


async def test_add_then_get_in_a_later_unit_of_work(
    uow_factory: UowFactory, new_account: Callable[[], Account]
) -> None:
    account = new_account()
    async with uow_factory() as uow:
        await uow.accounts.add(account)
        await uow.commit()
    async with uow_factory() as uow:
        assert await uow.accounts.get(account.id) == account


async def test_another_tenants_get_returns_none(
    uow_factory: UowFactory,
    new_account: Callable[[], Account],
    other_tenant: Callable[[], AbstractContextManager[RequestContext]],
) -> None:
    account = new_account()
    async with uow_factory() as uow:
        await uow.accounts.add(account)
        await uow.commit()
    with other_tenant():
        async with uow_factory() as uow:
            assert await uow.accounts.get(account.id) is None


async def test_adding_an_existing_id_is_a_conflict(
    uow_factory: UowFactory, new_account: Callable[[], Account]
) -> None:
    account = new_account()
    async with uow_factory() as uow:
        await uow.accounts.add(account)
        await uow.commit()
    async with uow_factory() as uow:
        with pytest.raises(Conflict):
            await uow.accounts.add(account)
        assert await uow.accounts.get(account.id) == account  # the unit of work is still usable
