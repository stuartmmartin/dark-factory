from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from fastapi import APIRouter, FastAPI

from sb_http.app import create_app
from sb_http.auth import DevHeaderAuth


@asynccontextmanager
async def _client_for(
    *routers: APIRouter,
    readiness: Sequence[Callable[[], Awaitable[bool]]] = (),
    raise_app_exceptions: bool = True,
    **app_kwargs: Any,
) -> AsyncIterator[httpx.AsyncClient]:
    app: FastAPI = create_app(
        title="t",
        version="0",
        routers=list(routers),
        auth=DevHeaderAuth(environment="test"),
        readiness=readiness,
        **app_kwargs,
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        yield client


@pytest.fixture
def client_for() -> Any:
    """Factory: `async with client_for(router, ...) as client`."""
    return _client_for
