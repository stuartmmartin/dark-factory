"""The AccountCountSnapshot workflow end to end on the time-skipping server and Postgres.

A re-run with the same workflow id replays the stored result through the activity's
deterministic idempotency key: one snapshot audit event per tenant and date (R3, D18).

`RECORD_HISTORY=1 make test ...` rewrites `histories/account_count_snapshot.json` from the first
run, for `test_replay.py`; commit the result.
"""

import asyncio
import json
import os
from collections.abc import Awaitable, Callable, Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy

from ledger.interface.workflows.account_count_snapshot import (
    AccountCountSnapshot,
    SnapshotInput,
    workflow_id_for,
)
from ledger.interface.workflows.activities import snapshot_account_count_activity
from sb_workflows.testing import time_skipping_env
from sb_workflows.worker import build_worker

type Seed = Callable[[UUID, int], Awaitable[None]]
type SnapshotAudits = Callable[[UUID, date], Awaitable[int]]
type StoredSnapshot = Callable[[UUID, date], Awaitable[int | None]]

TASK_QUEUE = "ledger-test"
RPC_TIMEOUT = timedelta(seconds=10)
HISTORY = Path(__file__).parent / "histories" / "account_count_snapshot.json"
SCRUBBED_IDENTITY = "recorder"


async def record_history(client: Client, workflow_id: str) -> None:
    """Write the workflow's history for the replay test, only when RECORD_HISTORY=1."""
    if os.environ.get("RECORD_HISTORY") != "1":
        return
    history = await client.get_workflow_handle(workflow_id).fetch_history(rpc_timeout=RPC_TIMEOUT)
    # Worker identities are "<pid>@<hostname>": scrub them so no machine name is committed.
    scrubbed = _scrub_identities(json.loads(history.to_json()))
    assert all("@" not in value for value in _identities(scrubbed))
    HISTORY.parent.mkdir(exist_ok=True)
    HISTORY.write_text(json.dumps(scrubbed, indent=2) + "\n")


def _scrub_identities(node: Any) -> Any:
    if isinstance(node, dict):
        return {
            k: SCRUBBED_IDENTITY if k == "identity" else _scrub_identities(v)
            for k, v in node.items()
        }
    if isinstance(node, list):
        return [_scrub_identities(v) for v in node]
    return node


def _identities(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "identity":
                yield str(v)
            else:
                yield from _identities(v)
    elif isinstance(node, list):
        for v in node:
            yield from _identities(v)


@pytest.mark.allow_network  # first run downloads the Temporal test server binary
@pytest.mark.usefixtures("bound_activity")
async def test_the_workflow_snapshots_the_count_and_a_rerun_replays(
    seed_accounts: Seed, snapshot_audits: SnapshotAudits, stored_snapshot: StoredSnapshot
) -> None:
    tenant: UUID = uuid4()
    as_of = date(2026, 9, 28)
    await seed_accounts(tenant, 2)
    wid = workflow_id_for(tenant, as_of)

    async with (
        asyncio.timeout(120),
        time_skipping_env() as env,
        build_worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[AccountCountSnapshot],
            activities=[snapshot_account_count_activity],
        ),
    ):
        first = await env.client.execute_workflow(
            AccountCountSnapshot.run,
            SnapshotInput(tenant_id=tenant, as_of=as_of),
            id=wid,
            task_queue=TASK_QUEUE,
            rpc_timeout=RPC_TIMEOUT,
        )
        await record_history(env.client, wid)
        second = await env.client.execute_workflow(
            AccountCountSnapshot.run,
            SnapshotInput(tenant_id=tenant, as_of=as_of),
            id=wid,
            task_queue=TASK_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            rpc_timeout=RPC_TIMEOUT,
        )

    assert first.accounts == 2
    assert first.as_of == as_of
    assert first.replayed is False
    assert await stored_snapshot(tenant, as_of) == 2
    assert second.replayed is True
    assert second.model_copy(update={"replayed": False}) == first
    assert await snapshot_audits(tenant, as_of) == 1  # R3, D18: the re-run wrote nothing
