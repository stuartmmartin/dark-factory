from datetime import UTC, datetime
from uuid import UUID

import pytest
from ledger_fakes import FakeLedgerUoW, LedgerState, fake_joined  # type: ignore[import-not-found]

from ledger.domain.accounts import Account
from sb_kernel.errors import Conflict, IdempotencyKeyReused
from sb_kernel.money import Currency


async def test_entering_twice_raises() -> None:
    uow = FakeLedgerUoW(LedgerState())
    async with uow:
        await uow.commit()
    with pytest.raises(RuntimeError, match="already entered"):
        await uow.__aenter__()


async def test_commit_after_finish_raises_and_rollback_after_commit_is_a_no_op() -> None:
    async with FakeLedgerUoW(LedgerState()) as uow:
        await uow.commit()
        await uow.rollback()  # no-op, as in SqlAlchemyUnitOfWork
        with pytest.raises(RuntimeError, match="already finished"):
            await uow.commit()


async def test_buffers_refuse_work_once_finished() -> None:
    async with FakeLedgerUoW(LedgerState()) as uow:
        await uow.rollback()
        with pytest.raises(RuntimeError):
            uow.audit.record(action="a", entity_type="t", entity_id="1", before=None, after=None)


async def test_joined_view_commit_is_a_no_op_and_the_owner_commits_once() -> None:
    state = LedgerState()
    async with FakeLedgerUoW(state) as outer:
        async with fake_joined(outer)() as inner:
            assert inner is outer
            await inner.commit()
            assert state.commits == 0
        await outer.commit()
    assert state.commits == 1


async def test_joined_view_needs_an_active_unit_of_work() -> None:
    with pytest.raises(RuntimeError, match="not active"):
        async with fake_joined(FakeLedgerUoW(LedgerState()))():
            pass


async def test_idempotency_save_raises_like_the_sql_store() -> None:
    state = LedgerState()
    async with FakeLedgerUoW(state) as uow:
        await uow.idempotency.save("k", "h1", {"x": 1})
        await uow.commit()
    async with FakeLedgerUoW(state) as uow:
        with pytest.raises(IdempotencyKeyReused):
            await uow.idempotency.save("k", "h2", {"x": 2})
    async with FakeLedgerUoW(state) as uow:
        with pytest.raises(Conflict):
            await uow.idempotency.save("k", "h1", {"x": 1})


@pytest.mark.parametrize(
    "after",
    [{"amount": 1.5}, {"at": datetime(2026, 3, 1, 12)}],  # noqa: DTZ001 - the naive case under test
    ids=["float", "naive-datetime"],
)
async def test_audit_rejects_what_the_sql_audit_log_rejects(after) -> None:
    async with FakeLedgerUoW(LedgerState()) as uow:
        with pytest.raises(TypeError):
            uow.audit.record(action="a", entity_type="t", entity_id="1", before=None, after=after)


async def test_audit_stores_a_canonical_copy_with_before_and_reason() -> None:
    state = LedgerState()
    after: dict[str, object] = {"id": UUID(int=1), "at": datetime(2026, 3, 1, 12, tzinfo=UTC)}
    async with FakeLedgerUoW(state) as uow:
        uow.audit.record(
            action="a", entity_type="t", entity_id="1", before={"n": 1}, after=after, reason="why"
        )
        after["id"] = "mutated after recording"
        await uow.commit()
    [record] = state.audit
    assert record.after == {"id": str(UUID(int=1)), "at": "2026-03-01T12:00:00+00:00"}
    assert record.before == {"n": 1}
    assert record.reason == "why"


async def test_idempotency_save_rejects_non_json_like_jsonb() -> None:
    async with FakeLedgerUoW(LedgerState()) as uow:
        with pytest.raises(TypeError):
            await uow.idempotency.save("k", "h", {"id": UUID(int=1)})


async def test_joined_view_refuses_a_finished_unit_of_work() -> None:
    async with FakeLedgerUoW(LedgerState()) as uow:
        await uow.commit()
        with pytest.raises(RuntimeError, match="not active"):
            async with fake_joined(uow)():
                pass


async def test_adding_an_account_id_twice_is_a_conflict() -> None:
    account = Account(
        id=UUID(int=1),
        tenant_id=UUID(int=0xF00D),
        name="Cash",
        currency=Currency.of("USD"),
        opened_at=datetime(2026, 3, 1, 12, tzinfo=UTC),
    )
    state = LedgerState()
    async with FakeLedgerUoW(state) as uow:
        await uow.accounts.add(account)
        with pytest.raises(Conflict):
            await uow.accounts.add(account)  # staged duplicate
        await uow.commit()
    async with FakeLedgerUoW(state) as uow:
        with pytest.raises(Conflict):
            await uow.accounts.add(account)  # committed duplicate
