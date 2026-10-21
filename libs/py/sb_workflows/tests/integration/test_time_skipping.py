"""A workflow that sleeps a simulated day finishes instantly and passes pydantic models."""

import asyncio
import time
from decimal import Decimal

import pytest
from sample_workflows import Greeting, Payment, QuotePrice, SleepThenGreet, greet, price

from sb_workflows.testing import time_skipping_env
from sb_workflows.worker import build_worker


@pytest.mark.allow_network  # first run downloads the Temporal test server binary
async def test_day_long_sleep_is_skipped() -> None:
    start = time.monotonic()
    async with (
        asyncio.timeout(60),
        time_skipping_env() as env,
        build_worker(env.client, task_queue="tq", workflows=[SleepThenGreet], activities=[greet]),
    ):
        result = await env.client.execute_workflow(
            SleepThenGreet.run, Greeting(name="ada"), id="wf-1", task_queue="tq"
        )
    assert result == "hello ada"
    assert time.monotonic() - start < 30


@pytest.mark.allow_network
async def test_decimal_money_round_trips_through_sandbox() -> None:
    async with (
        asyncio.timeout(60),
        time_skipping_env() as env,
        build_worker(env.client, task_queue="tq2", workflows=[QuotePrice], activities=[price]),
    ):
        result = await env.client.execute_workflow(
            QuotePrice.run, Greeting(name="ada"), id="wf-2", task_queue="tq2"
        )
    assert result == Payment(amount=Decimal("12.345"), currency="USD")
    assert isinstance(result.amount, Decimal)
