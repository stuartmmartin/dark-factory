"""Sample workflow and activity. Kept out of the test module because the workflow sandbox
re-imports the workflow's module by name, and pytest's importlib mode gives test modules names
that are not importable."""

from datetime import timedelta
from decimal import Decimal

from pydantic import BaseModel
from temporalio import activity, workflow

from sb_kernel.money import Money


class Greeting(BaseModel):
    name: str


@activity.defn
async def greet(inp: Greeting) -> str:
    return f"hello {inp.name}"


@workflow.defn
class SleepThenGreet:
    @workflow.run
    async def run(self, inp: Greeting) -> str:
        await workflow.sleep(timedelta(days=1))
        return await workflow.execute_activity(
            greet, inp, start_to_close_timeout=timedelta(seconds=10)
        )


class Payment(BaseModel):
    amount: Decimal
    currency: str


@activity.defn
async def price(inp: Greeting) -> Payment:
    money = Money.of("12.345", "USD")  # sb_kernel is passed through the sandbox, not re-imported
    return Payment(amount=money.amount, currency=money.currency.code)


@workflow.defn
class QuotePrice:
    @workflow.run
    async def run(self, inp: Greeting) -> Payment:
        return await workflow.execute_activity(
            price, inp, start_to_close_timeout=timedelta(seconds=10)
        )
