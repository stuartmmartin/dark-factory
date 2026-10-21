from datetime import UTC, date, datetime

import pytest

from ledger.application.dto import (
    OpenAccountCommand,
    RecordAccountOpenedCommand,
    SnapshotAccountCountCommand,
)
from ledger.application.use_cases.open_account import OpenAccount
from ledger.application.use_cases.record_account_opened import RecordAccountOpened
from ledger.application.use_cases.snapshot_account_count import SnapshotAccountCount
from sb_kernel.clock import FixedClock
from sb_kernel.errors import IdempotencyKeyReused

CLOCK = FixedClock(datetime(2026, 3, 1, 12, tzinfo=UTC))
AS_OF = date(2026, 3, 1)


async def count_one(uow) -> None:
    account = await OpenAccount(uow, CLOCK)(OpenAccountCommand(name="Cash", currency="USD"))
    await RecordAccountOpened(uow)(RecordAccountOpenedCommand(account_id=account.id))


async def test_R1_snapshot_is_the_current_count_and_a_rerun_overwrites_the_date(
    uow, state, tenant_context
) -> None:
    snapshot = SnapshotAccountCount(uow)
    await count_one(uow)
    first = await snapshot(SnapshotAccountCountCommand(as_of=AS_OF))
    await count_one(uow)
    second = await snapshot(SnapshotAccountCountCommand(as_of=AS_OF))
    assert (first.accounts, second.accounts) == (1, 2)
    assert not second.replayed
    assert state.snapshots == {(tenant_context.tenant_id, AS_OF): 2}


def snapshots_audited(state) -> list[dict[str, object] | None]:
    return [a.after for a in state.audit if a.action == "account_count.snapshot"]


async def test_R2_one_audit_event_records_the_date_and_count(uow, state) -> None:
    await count_one(uow)
    await SnapshotAccountCount(uow)(SnapshotAccountCountCommand(as_of=AS_OF))
    assert snapshots_audited(state) == [{"as_of": "2026-03-01", "accounts": 1}]


async def test_R3_a_retry_with_the_same_key_replays_and_writes_nothing(uow, state) -> None:
    await count_one(uow)
    snapshot = SnapshotAccountCount(uow)
    command = SnapshotAccountCountCommand(as_of=AS_OF, idempotency_key="wf-2026-03-01")
    first = await snapshot(command)
    commits, audited = state.commits, len(state.audit)
    second = await snapshot(command)  # the Temporal activity retry (D18)
    assert second == first.model_copy(update={"replayed": True})
    assert state.commits == commits
    assert len(state.audit) == audited


async def test_R3_same_key_different_request_is_idempotency_key_reused(uow, state) -> None:
    snapshot = SnapshotAccountCount(uow)
    await snapshot(SnapshotAccountCountCommand(as_of=AS_OF, idempotency_key="wf-1"))
    with pytest.raises(IdempotencyKeyReused):
        await snapshot(SnapshotAccountCountCommand(as_of=date(2026, 3, 2), idempotency_key="wf-1"))
    assert len(snapshots_audited(state)) == 1
