"""Time-skipping Temporal test environment with the pydantic data converter."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment


@asynccontextmanager
async def time_skipping_env() -> AsyncGenerator[WorkflowEnvironment]:
    """`async with time_skipping_env() as env:` (test server is x64; Rosetta on Apple Silicon)."""
    env = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    try:
        yield env
    finally:
        await env.shutdown()
