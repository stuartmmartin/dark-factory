"""`AccountCountSnapshot`: snapshot one tenant's account count for one date.

The workflow runs one activity, `snapshot_account_count_activity`, which calls the
`SnapshotAccountCount` use case (the rules live there). The workflow id is deterministic
(`workflow_id_for`): starting a second run for the same tenant and date while one is running is
rejected, and a later re-run replays the stored result through the activity's idempotency key.

Determinism (A12, D16): no I/O, no `Clock`, no `datetime.now()` here; the activity and its DTOs
and `sb_workflows.ids` are imported through `workflow.unsafe.imports_passed_through()`.

No schedule: the thin slice starts this workflow from its tests only (D16). A schedule cannot
carry a per-tenant input, so adding one later means one schedule per tenant.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from ledger.application.dto import SnapshotResult
    from ledger.interface.workflows.activities import (
        SnapshotInput,
        snapshot_account_count_activity,
    )
    from sb_workflows.ids import workflow_id

__all__ = ["AccountCountSnapshot", "SnapshotInput", "workflow_id_for"]

WORKFLOW_NAME = "account-count-snapshot"
ACTIVITY_TIMEOUT = timedelta(minutes=1)
ACTIVITY_RETRY = RetryPolicy(maximum_attempts=5)


def workflow_id_for(tenant_id: UUID, as_of: date) -> str:
    """The one workflow id for a tenant and date (the activity's idempotency key too)."""
    return workflow_id(WORKFLOW_NAME, tenant_id, as_of.isoformat())


@workflow.defn
class AccountCountSnapshot:
    @workflow.run
    async def run(self, inp: SnapshotInput) -> SnapshotResult:
        return await workflow.execute_activity(
            snapshot_account_count_activity,
            inp,
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=ACTIVITY_RETRY,
        )
