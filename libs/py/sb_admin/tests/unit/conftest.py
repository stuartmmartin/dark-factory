import decimal
from collections.abc import AsyncIterator, Callable
from decimal import Decimal

import httpx
import pytest
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.applications import Starlette
from starlette.routing import Mount

from sb_admin.acceptor import Acceptor, InputRejected
from sb_admin.admin import create_admin
from sb_admin.auth import DevAdminAuth
from sb_kernel.errors import CurrencyMismatch, DomainError, ValidationFailed


class SplitInput(BaseModel):
    total: Decimal = Field(description="Amount to split")
    parts: int = Field(gt=0, le=100)


class SplitOutput(BaseModel):
    each: Decimal


def split(inp: SplitInput) -> SplitOutput:  # a pure policy stand-in
    return SplitOutput(each=inp.total / inp.parts)


SPLIT = Acceptor("split", "Split", SplitInput, split, version="1")


class StrictInput(BaseModel):
    n: int


def strict(inp: StrictInput) -> SplitOutput:
    raise InputRejected("policy says no")


STRICT = Acceptor("strict", "Strict", StrictInput, strict, version="1")


def boom(inp: StrictInput) -> SplitOutput:
    raise ValueError("secret internal detail")


BOOM = Acceptor("boom", "Boom", StrictInput, boom, version="1")


def divide(inp: StrictInput) -> SplitOutput:
    return SplitOutput(each=Decimal(1) / Decimal(0))  # raises decimal.DivisionByZero


DIVIDE = Acceptor("divide", "Divide", StrictInput, divide, version="1")
assert issubclass(decimal.DivisionByZero, ArithmeticError)


class RichInput(BaseModel):
    prices: list[Decimal]
    amount: Decimal | None = None
    count: int | None = None
    note: str = "dflt"


class RichOutput(BaseModel):
    total: Decimal
    count: int | None
    note: str


def rich(inp: RichInput) -> RichOutput:
    return RichOutput(
        total=sum(inp.prices, Decimal(0)) + (inp.amount or Decimal(0)),
        count=inp.count,
        note=inp.note,
    )


RICH = Acceptor("rich", "Rich", RichInput, rich, version="7")


class EchoInput(BaseModel):
    text: str = Field(title="<u>LABEL</u>", description="<s>HELP</s>")


class EchoOutput(BaseModel):
    text: str


def echo(inp: EchoInput) -> EchoOutput:
    if inp.text == "reject":
        raise InputRejected("<script>rej()</script>")
    return EchoOutput(text=inp.text)


ECHO = Acceptor("echo", "<b>TITLE</b>", EchoInput, echo, version="1", description="<i>DESC</i>")


def kernel_error(inp: StrictInput) -> SplitOutput:
    errors: dict[int, DomainError] = {
        1: ValidationFailed("amount does not fit <NUMERIC>"),
        2: CurrencyMismatch("USD vs EUR"),
        3: DomainError("plain domain refusal"),
    }
    raise errors[inp.n]


KERNEL = Acceptor("kernel", "Kernel", StrictInput, kernel_error, version="1")
ALL = [SPLIT, STRICT, BOOM, DIVIDE, RICH, ECHO, KERNEL]


def _make_auth(environment: str = "test") -> DevAdminAuth:
    return DevAdminAuth("k" * 32, "admin", "pw", environment=environment)


def _make_admin(mount_path: str = "/admin", environment: str = "test") -> Starlette:
    # SQLAdmin needs an engine; acceptor views never query this placeholder.
    return create_admin(
        create_async_engine("sqlite+aiosqlite://"),
        title="t",
        auth=_make_auth(environment),
        acceptors=ALL,
        mount_path=mount_path,
    )


@pytest.fixture
def make_auth() -> Callable[..., DevAdminAuth]:
    return _make_auth


@pytest.fixture
def make_admin() -> Callable[..., Starlette]:
    return _make_admin


@pytest.fixture
def admin_asgi() -> Starlette:
    return _make_admin()


@pytest.fixture
async def anon(admin_asgi: Starlette) -> AsyncIterator[httpx.AsyncClient]:
    app = Starlette(routes=[Mount("/admin", app=admin_asgi)])
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


@pytest.fixture
async def client(anon: httpx.AsyncClient) -> httpx.AsyncClient:
    response = await anon.post("/admin/login", data={"username": "admin", "password": "pw"})
    assert response.status_code == 302
    return anon
