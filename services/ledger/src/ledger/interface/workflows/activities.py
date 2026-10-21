"""Temporal activities of the ledger: each restores the tenant context and calls one use case.

`snapshot_account_count_activity` runs `SnapshotAccountCount` for the tenant and date in its
input. Temporal retries activities, so it passes the workflow id as the idempotency key: the id
already encodes the tenant and the date (`workflow_id_for`), so a retried attempt replays the
stored result instead of writing a second audit event (D18, R3). An overlapping attempt gets
`Conflict` from the idempotency store; it is left retryable, so the next attempt replays.
`ValidationFailed` (including `IdempotencyKeyReused`) cannot succeed on retry, so it becomes a
non-retryable `ApplicationError` carrying the same message, with the error code as its type.

Wiring: `bind(container)` is the only module-level state here and the one place the activity
gets its use case. `ledger.worker` calls it at startup (and the tests call it) before the worker
runs. Nothing is bound at import time.

The tenant id and actor in the input are trusted because only our services can start workflows
(docs/architecture/workflows.md, "Trust boundary").
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from temporalio import activity
from temporalio.exceptions import ApplicationError

from ledger.application.dto import SnapshotAccountCountCommand, SnapshotResult
from sb_kernel.context import RequestContext, use_context
from sb_kernel.errors import ValidationFailed

__all__ = ["SnapshotContainer", "SnapshotInput", "bind", "snapshot_account_count_activity"]

SYSTEM_ACTOR = "system:snapshot"


class SnapshotInput(BaseModel):
    """The workflow's and the activity's input. Re-exported by `account_count_snapshot`."""

    model_config = ConfigDict(frozen=True)

    tenant_id: UUID
    as_of: date
    actor: str = SYSTEM_ACTOR


class SnapshotContainer(Protocol):
    """What the activity needs from `ledger.bootstrap.Container` (interface cannot import it):
    its `SnapshotAccountCount` use case."""

    @property
    def snapshot_account_count(
        self,
    ) -> Callable[[SnapshotAccountCountCommand], Awaitable[SnapshotResult]]: ...


_container: SnapshotContainer | None = None


def bind(container: SnapshotContainer) -> None:
    """Give the activities their use cases; call before the worker starts."""
    global _container  # noqa: PLW0603 - the documented activity wiring point
    _container = container


def _bound() -> SnapshotContainer:
    if _container is None:
        raise RuntimeError("activities are not bound: call activities.bind(container) first")
    return _container


@activity.defn
async def snapshot_account_count_activity(inp: SnapshotInput) -> SnapshotResult:
    workflow_id = activity.info().workflow_id
    if workflow_id is None:  # the key must be deterministic: never run outside a workflow
        raise RuntimeError("snapshot_account_count_activity must run inside a workflow")
    context = RequestContext(tenant_id=inp.tenant_id, actor=inp.actor, request_id=workflow_id)
    command = SnapshotAccountCountCommand(as_of=inp.as_of, idempotency_key=workflow_id)
    with use_context(context):
        try:
            return await _bound().snapshot_account_count(command)
        except ValidationFailed as exc:  # Conflict and the rest stay retryable
            raise ApplicationError(exc.message, type=exc.code, non_retryable=True) from exc
