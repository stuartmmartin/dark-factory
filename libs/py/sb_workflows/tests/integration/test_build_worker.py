"""`build_worker` passes a bounded graceful shutdown to the Worker (10 s by default).

Needs a connected client: temporalio refuses lazy clients for workers, so this is not a unit test.
"""

import asyncio
from datetime import timedelta

import pytest
from sample_workflows import greet

from sb_workflows.testing import time_skipping_env
from sb_workflows.worker import build_worker


@pytest.mark.allow_network  # first run downloads the Temporal test server binary
async def test_graceful_shutdown_defaults_to_ten_seconds_and_can_be_set() -> None:
    async with asyncio.timeout(60), time_skipping_env() as env:
        default = build_worker(env.client, task_queue="tq-gs-1", workflows=[], activities=[greet])
        custom = build_worker(
            env.client,
            task_queue="tq-gs-2",
            workflows=[],
            activities=[greet],
            graceful_shutdown_timeout=timedelta(seconds=3),
        )
    assert default.config().get("graceful_shutdown_timeout") == timedelta(seconds=10)
    assert custom.config().get("graceful_shutdown_timeout") == timedelta(seconds=3)
