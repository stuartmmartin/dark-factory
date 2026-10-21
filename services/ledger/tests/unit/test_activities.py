"""How the snapshot activity reports use case errors to Temporal.

- `Conflict` (an overlapping attempt holds the idempotency key) stays retryable: it is raised
  as-is, not wrapped in a non-retryable `ApplicationError`, so the next attempt replays.
- `ValidationFailed` and its subclass `IdempotencyKeyReused` can never succeed on retry: they
  become `ApplicationError(non_retryable=True)` with the original message.
"""

import dataclasses
from dataclasses import dataclass
from datetime import date
from uuid import uuid4

import pytest
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from ledger.application.dto import SnapshotAccountCountCommand, SnapshotResult
from ledger.interface.workflows import activities
from ledger.interface.workflows.account_count_snapshot import SnapshotInput, workflow_id_for
from sb_kernel.errors import Conflict, DomainError, IdempotencyKeyReused, ValidationFailed


@dataclass(frozen=True)
class _Raising:
    error: DomainError

    async def __call__(self, _: SnapshotAccountCountCommand) -> SnapshotResult:
        raise self.error


@dataclass(frozen=True)
class _Container:
    snapshot_account_count: _Raising


async def _run_with(error: DomainError) -> None:
    activities.bind(_Container(_Raising(error)))
    tenant, as_of = uuid4(), date(2026, 9, 28)
    env = ActivityEnvironment()
    env.info = dataclasses.replace(
        ActivityEnvironment.default_info(), workflow_id=workflow_id_for(tenant, as_of)
    )
    await env.run(
        activities.snapshot_account_count_activity, SnapshotInput(tenant_id=tenant, as_of=as_of)
    )


async def test_a_conflict_stays_retryable() -> None:
    with pytest.raises(Conflict, match="in flight") as raised:
        await _run_with(Conflict("request in flight"))
    assert not isinstance(raised.value, ApplicationError)


@pytest.mark.parametrize(
    "error",
    [ValidationFailed("bad date"), IdempotencyKeyReused("key used for a different request")],
    ids=["validation_failed", "idempotency_key_reused"],
)
async def test_validation_errors_are_non_retryable_with_their_message(
    error: DomainError,
) -> None:
    with pytest.raises(ApplicationError) as raised:
        await _run_with(error)
    assert raised.value.non_retryable is True
    assert raised.value.message == error.message
    assert raised.value.type == error.code
