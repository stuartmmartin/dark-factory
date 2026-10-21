from datetime import UTC, datetime
from uuid import UUID

import pytest
from ledger_fakes import FakeLedgerUoW, fake_joined  # type: ignore[import-not-found]

from ledger.application.dto import OpenAccountCommand, RecordAccountOpenedCommand
from ledger.application.use_cases.open_account import OpenAccount
from ledger.application.use_cases.record_account_opened import RecordAccountOpened
from sb_kernel.clock import FixedClock
from sb_kernel.context import RequestContext, use_context
from sb_kernel.errors import NotFound

CLOCK = FixedClock(datetime(2026, 3, 1, 12, tzinfo=UTC))
OTHER = RequestContext(tenant_id=UUID(int=2), actor="other", request_id="req-2")


async def opened(uow, name: str = "Operating cash") -> UUID:
    return (await OpenAccount(uow, CLOCK)(OpenAccountCommand(name=name, currency="USD"))).id


async def test_R1_increments_the_current_tenants_count(uow, state, tenant_context) -> None:
    with use_context(OTHER):
        theirs = await opened(uow)
        assert (
            await RecordAccountOpened(uow)(RecordAccountOpenedCommand(account_id=theirs))
        ).accounts == 1
    record = RecordAccountOpened(uow)
    first = await record(RecordAccountOpenedCommand(account_id=await opened(uow, "A")))
    second = await record(RecordAccountOpenedCommand(account_id=await opened(uow, "B")))
    assert (first.accounts, second.accounts) == (1, 2)
    assert state.counts == {tenant_context.tenant_id: 2, OTHER.tenant_id: 1}


def increments(state) -> list[tuple[str, str, dict[str, object] | None]]:
    return [
        (a.entity_type, a.entity_id, a.after)
        for a in state.audit
        if a.action == "account_count.increment"
    ]


async def test_R2_one_audit_event_per_count_with_the_new_count(uow, state) -> None:
    a, b = await opened(uow, "A"), await opened(uow, "B")
    record = RecordAccountOpened(uow)
    await record(RecordAccountOpenedCommand(account_id=a))
    await record(RecordAccountOpenedCommand(account_id=b))
    assert increments(state) == [
        ("account_count", str(a), {"accounts": 1}),
        ("account_count", str(b), {"accounts": 2}),
    ]


async def test_R3_unknown_account_is_not_found_and_nothing_is_counted(uow, state) -> None:
    commits = state.commits
    with pytest.raises(NotFound):
        await RecordAccountOpened(uow)(RecordAccountOpenedCommand(account_id=UUID(int=404)))
    assert state.counts == {}
    assert state.commits == commits
    assert not increments(state)


async def test_R3_another_tenants_account_is_not_found(uow, state) -> None:
    with use_context(OTHER):
        theirs = await opened(uow)
    with pytest.raises(NotFound):
        await RecordAccountOpened(uow)(RecordAccountOpenedCommand(account_id=theirs))
    assert state.counts == {}


class HandlerError(RuntimeError):
    """A consumer handler failing after the use case ran, before the inbox commits."""


async def handle_then_fail(state, account) -> None:
    async with FakeLedgerUoW(state) as outer:  # the inbox's transaction (D13)
        result = await RecordAccountOpened(fake_joined(outer))(
            RecordAccountOpenedCommand(account_id=account)
        )
        assert result.accounts == 1
        raise HandlerError  # before outer.commit()


async def test_joined_abort_commits_nothing(uow, state) -> None:
    account = await opened(uow)
    commits = state.commits
    with pytest.raises(HandlerError):
        await handle_then_fail(state, account)
    assert state.counts == {}
    assert not increments(state)
    assert state.commits == commits


async def test_joined_use_case_commits_once_with_its_owner(uow, state, tenant_context) -> None:
    account = await opened(uow)
    commits = state.commits
    async with FakeLedgerUoW(state) as outer:
        await RecordAccountOpened(fake_joined(outer))(
            RecordAccountOpenedCommand(account_id=account)
        )
        assert state.commits == commits  # the joined commit() was a no-op
        await outer.commit()
    assert state.counts == {tenant_context.tenant_id: 1}
    assert state.commits == commits + 1
    assert increments(state) == [("account_count", str(account), {"accounts": 1})]
