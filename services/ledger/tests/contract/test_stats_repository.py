"""AccountStatsRepository contract: fake and SQL behave the same."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date

from ledger.application.ports import UowFactory
from sb_kernel.context import RequestContext

AS_OF = date(2026, 3, 1)


async def test_count_is_zero_before_anything(uow_factory: UowFactory) -> None:
    async with uow_factory() as uow:
        assert await uow.stats.count() == 0


async def test_increments_in_separate_units_of_work_return_one_then_two(
    uow_factory: UowFactory,
) -> None:
    results: list[int] = []
    for _ in range(2):
        async with uow_factory() as uow:
            results.append(await uow.stats.increment())
            await uow.commit()
    assert results == [1, 2]
    async with uow_factory() as uow:
        assert await uow.stats.count() == 2


async def test_another_tenants_count_stays_zero(
    uow_factory: UowFactory, other_tenant: Callable[[], AbstractContextManager[RequestContext]]
) -> None:
    async with uow_factory() as uow:
        await uow.stats.increment()
        await uow.commit()
    with other_tenant():
        async with uow_factory() as uow:
            assert await uow.stats.count() == 0
            assert await uow.stats.increment() == 1  # its own count starts at one


async def test_upsert_snapshot_twice_keeps_the_second_value(uow_factory: UowFactory) -> None:
    for accounts in (3, 5):
        async with uow_factory() as uow:
            await uow.stats.upsert_snapshot(AS_OF, accounts)
            await uow.commit()
    async with uow_factory() as uow:
        assert await uow.stats.snapshot(AS_OF) == 5


async def test_snapshot_of_an_unknown_date_is_none(uow_factory: UowFactory) -> None:
    async with uow_factory() as uow:
        await uow.stats.upsert_snapshot(AS_OF, 3)
        await uow.commit()
    async with uow_factory() as uow:
        assert await uow.stats.snapshot(date(2026, 3, 2)) is None


async def test_snapshots_are_per_tenant(
    uow_factory: UowFactory, other_tenant: Callable[[], AbstractContextManager[RequestContext]]
) -> None:
    async with uow_factory() as uow:
        await uow.stats.upsert_snapshot(AS_OF, 3)
        await uow.commit()
    with other_tenant():
        async with uow_factory() as uow:
            assert await uow.stats.snapshot(AS_OF) is None
