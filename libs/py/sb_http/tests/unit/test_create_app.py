from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from fastapi import APIRouter

from sb_http.app import create_app
from sb_http.auth import DevHeaderAuth


def _router(*paths: str) -> APIRouter:
    r = APIRouter()
    for i, p in enumerate(paths):

        async def handler() -> dict[str, str]:
            return {"ok": "yes"}

        handler.__name__ = f"handler_{i}"
        r.add_api_route(p, handler, methods=["GET"])
    return r


def _build(*routers: APIRouter, **kw: Any) -> Any:
    return create_app(
        title="t", version="0", routers=list(routers), auth=DevHeaderAuth(environment="test"), **kw
    )


@pytest.mark.parametrize(
    "path",
    ["/{x}", "/{a}/{b}", "/{rest:path}", "/health/{x}", "/{a}/live", "/docs/{x}"],
)
def test_route_colliding_with_public_path_fails_at_build(path: str) -> None:
    with pytest.raises(ValueError, match="public"):
        _build(_router(path), expose_docs=True)


def test_route_colliding_with_admin_prefix_fails_at_build() -> None:
    with pytest.raises(ValueError, match="public"):
        _build(_router("/admin"))
    with pytest.raises(ValueError, match="public"):
        _build(_router("/admin/{x}"))


def test_normal_routes_build() -> None:
    _build(_router("/things", "/things/{id}", "/a/b/c"))


async def test_unauthenticated_normal_routes_are_403() -> None:
    app = _build(_router("/things", "/things/{id}"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/things")).status_code == 403
        assert (await c.get("/things/1")).status_code == 403


async def test_docs_are_hidden_by_default() -> None:
    app = _build(_router("/things"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        for p in ("/docs", "/openapi.json", "/redoc", "/docs/oauth2-redirect"):
            assert (await c.get(p)).status_code == 403
    assert app.openapi_url is None
    assert app.docs_url is None


async def test_docs_exposed_when_requested() -> None:
    app = _build(_router("/things"), expose_docs=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/docs")).status_code == 200
        assert (await c.get("/openapi.json")).status_code == 200
        assert (await c.get("/docs/oauth2-redirect")).status_code == 200


@pytest.mark.parametrize("path", ["/{x}", "/health/{x}", "/admin/{x}", "/{a}/{b}"])
def test_websocket_route_colliding_with_public_path_fails_at_build(path: str) -> None:
    async def handler() -> None: ...

    r = APIRouter()
    r.add_api_websocket_route(path, handler)
    with pytest.raises(ValueError, match="public"):
        _build(r)


@pytest.mark.filterwarnings("ignore:Duplicate Operation ID")
async def test_duplicate_operation_ids_from_late_routes_fail_at_startup() -> None:
    app = _build(_router("/things"))

    async def same() -> None: ...

    app.add_api_route("/late-a", same, methods=["GET"])
    app.add_api_route("/late-b", same, methods=["GET"])
    with pytest.raises(ValueError, match="operation id"):
        async with app.router.lifespan_context(app):
            pass


async def test_startup_check_passes_and_user_lifespan_runs() -> None:
    events: list[str] = []

    @asynccontextmanager
    async def lifespan(_: Any) -> AsyncGenerator[None]:
        events.append("up")
        yield
        events.append("down")

    app = _build(_router("/things"), lifespan=lifespan)
    async with app.router.lifespan_context(app):
        pass
    assert events == ["up", "down"]


async def test_root_path_health_live_is_public() -> None:
    app = _build(_router("/things"))
    app.root_path = "/api"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/api/health/live")).status_code == 200
        assert (await c.get("/api/things")).status_code == 403


@pytest.mark.filterwarnings("ignore:Duplicate Operation ID")
def test_duplicate_operation_ids_fail_at_build() -> None:
    a, b = APIRouter(), APIRouter()

    async def same() -> None: ...

    a.add_api_route("/a", same, methods=["GET"])
    b.add_api_route("/b", same, methods=["GET"])
    with pytest.raises(ValueError, match="operation id"):
        _build(a, b)
