"""A Temporal retry of the snapshot activity (Review Focus #4, D18).

A retry runs the activity again with the same input and the same workflow id. The workflow id
is the idempotency key, so the second attempt replays the stored result: one audit event, and
equal results apart from `replayed`.
"""

import dataclasses
from collections.abc import Awaitable, Callable
from datetime import date
from uuid import UUID, uuid4

import pytest
from temporalio.testing import ActivityEnvironment

from ledger.interface.workflows.account_count_snapshot import SnapshotInput, workflow_id_for
from ledger.interface.workflows.activities import snapshot_account_count_activity

type Seed = Callable[[UUID, int], Awaitable[None]]
type SnapshotAudits = Callable[[UUID, date], Awaitable[int]]


@pytest.mark.usefixtures("bound_activity")
async def test_a_retried_activity_replays_and_writes_one_audit_event(
    seed_accounts: Seed, snapshot_audits: SnapshotAudits
) -> None:
    tenant = uuid4()
    as_of = date(2026, 9, 27)
    await seed_accounts(tenant, 2)
    env = ActivityEnvironment()
    env.info = dataclasses.replace(
        ActivityEnvironment.default_info(), workflow_id=workflow_id_for(tenant, as_of)
    )
    inp = SnapshotInput(tenant_id=tenant, as_of=as_of)

    first = await env.run(snapshot_account_count_activity, inp)
    retried = await env.run(snapshot_account_count_activity, inp)

    assert first.accounts == 2
    assert first.replayed is False
    assert retried.replayed is True
    assert retried.model_copy(update={"replayed": False}) == first
    assert await snapshot_audits(tenant, as_of) == 1
