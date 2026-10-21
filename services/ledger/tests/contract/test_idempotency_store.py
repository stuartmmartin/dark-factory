"""IdempotencyStore contract (D14, D15): fake and SQL behave the same."""

from collections.abc import Callable
from contextlib import AbstractContextManager

import pytest

from ledger.application.ports import UowFactory
from sb_kernel.context import RequestContext
from sb_kernel.errors import Conflict, IdempotencyKeyReused
from sb_kernel.uow import StoredResponse

KEY = "open-account:1"
RESPONSE = {"id": "a1", "accounts": 1}


async def _save(uow_factory: UowFactory, request_hash: str = "h1") -> None:
    async with uow_factory() as uow:
        await uow.idempotency.save(KEY, request_hash, RESPONSE)
        await uow.commit()


async def test_save_then_get_in_a_later_unit_of_work(uow_factory: UowFactory) -> None:
    await _save(uow_factory)
    async with uow_factory() as uow:
        assert await uow.idempotency.get(KEY) == StoredResponse("h1", RESPONSE)
        assert await uow.idempotency.get("unknown") is None


async def test_same_key_different_hash_is_idempotency_key_reused(
    uow_factory: UowFactory,
) -> None:
    await _save(uow_factory)
    async with uow_factory() as uow:
        with pytest.raises(IdempotencyKeyReused):
            await uow.idempotency.save(KEY, "h2", RESPONSE)


async def test_same_key_same_hash_is_a_conflict(uow_factory: UowFactory) -> None:
    await _save(uow_factory)
    async with uow_factory() as uow:
        with pytest.raises(Conflict) as raised:
            await uow.idempotency.save(KEY, "h1", RESPONSE)
        assert not isinstance(raised.value, IdempotencyKeyReused)


async def test_keys_are_per_tenant(
    uow_factory: UowFactory, other_tenant: Callable[[], AbstractContextManager[RequestContext]]
) -> None:
    await _save(uow_factory)
    with other_tenant():
        async with uow_factory() as uow:
            assert await uow.idempotency.get(KEY) is None
        await _save(uow_factory, "h2")  # the same key is free in another tenant
