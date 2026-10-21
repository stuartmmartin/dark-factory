"""The ledger API over ASGI with dev header auth (the `app` fixture is in ../conftest.py)."""

from collections.abc import AsyncIterator, Callable
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://ledger") as c:
        yield c


@pytest.fixture
def tenant() -> UUID:
    """A fresh tenant per test: never rely on rows from another test."""
    return uuid4()


@pytest.fixture
def as_tenant(tenant: UUID) -> Callable[..., dict[str, str]]:
    """Dev-auth headers for `tenant` (or another), plus any extra headers."""

    def headers(other: UUID | None = None, **extra: str) -> dict[str, str]:
        return {"X-Tenant-Id": str(other or tenant), "X-Actor": "tester", **extra}

    return headers
