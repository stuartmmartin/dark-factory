"""Auth-exemption behaviour, driven over raw ASGI against a real app."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI, WebSocket
from fastapi.responses import StreamingResponse
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import BaseRoute, Route
from starlette.types import Message, Receive, Scope, Send

from sb_http import middleware as mw
from sb_http.app import create_app, mount_admin
from sb_http.auth import DevHeaderAuth

TID = b"11111111-1111-1111-1111-111111111111"
AUTH = [(b"x-tenant-id", TID)]


async def _sub(scope: Scope, receive: Receive, send: Send) -> None:
    """Stand-in for a self-authenticating admin app."""
    if scope["type"] == "http":
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"admin"})


def _app(auth: Any = None, **kw: Any) -> FastAPI:
    r = APIRouter()

    @r.get("/things")
    async def things() -> dict[str, str]:
        return {"ok": "yes"}

    @r.get("/stream")
    async def stream() -> StreamingResponse:
        async def gen() -> AsyncIterator[bytes]:
            yield b"first"
            raise RuntimeError("late failure")

        return StreamingResponse(gen())

    return create_app(
        title="t",
        version="0",
        routers=[r],
        auth=auth or DevHeaderAuth(environment="test"),
        **kw,
    )


async def _call(
    app: FastAPI,
    path: str,
    *,
    kind: str = "http",
    root_path: str = "",
    headers: list[tuple[bytes, bytes]] | None = None,
    method: str = "GET",
) -> list[Message]:
    sent: list[Message] = []
    inbox: list[Message] = (
        [{"type": "websocket.connect"}]
        if kind == "websocket"
        else [{"type": "http.request", "body": b"", "more_body": False}]
    )

    async def receive() -> Message:
        return inbox.pop(0) if inbox else {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        sent.append(message)

    scope: Scope = {
        "type": kind,
        "path": path,
        "root_path": root_path,
        "headers": headers or [],
        "query_string": b"",
        "method": method,
        "scheme": "ws" if kind == "websocket" else "http",
        "server": ("t", 80),
        "client": ("c", 1),
        "http_version": "1.1",
    }
    await app(scope, receive, send)
    return sent


def _status(sent: list[Message]) -> int:
    return int(sent[0]["status"])


@pytest.mark.parametrize("path", ["/health/live", "/health/ready"])
async def test_health_routes_need_no_auth(path: str) -> None:
    assert _status(await _call(_app(), path)) == 200


@pytest.mark.parametrize(
    "path",
    [
        "/health/live/x",
        "/health-evil",
        "/",
        "/x",
        "/things",
        "/admin",
        "/admin/",
        "/admin/x",
        "/admin/users",
        "/admin/x/z",
        "/admin/x/detail",
        "/docs",
        "/openapi.json",
    ],
)
async def test_everything_else_needs_auth_including_404s(path: str) -> None:
    assert _status(await _call(_app(), path)) == 403


async def test_post_to_health_route_is_not_exempt() -> None:
    assert _status(await _call(_app(), "/health/live", method="POST")) == 403


async def test_authenticated_request_reaches_route() -> None:
    assert _status(await _call(_app(), "/things", headers=AUTH)) == 200


@pytest.mark.parametrize(
    ("path", "status"),
    [
        ("/admin/", 200),
        ("/admin/users/1", 200),
        ("/admin", 307),
        ("/admin-x", 403),
        ("/administrator", 403),
    ],
)
async def test_mount_admin_is_reachable_without_sb_http_auth(path: str, status: int) -> None:
    app = _app()
    mount_admin(app, _sub)
    assert _status(await _call(app, path)) == status


async def test_mount_admin_leaves_other_routes_protected() -> None:
    app = _app()
    mount_admin(app, _sub)
    assert _status(await _call(app, "/things")) == 403
    assert _status(await _call(app, "/health/live")) == 200


async def test_mount_admin_uses_the_mount_path_the_admin_app_declares() -> None:
    declared = Starlette(routes=[Route("/", PlainTextResponse("ops"))])
    declared.state.mount_path = "/ops"
    app = _app()
    mount_admin(app, declared)
    assert _status(await _call(app, "/ops/")) == 200
    assert _status(await _call(app, "/admin/")) == 403


def test_mount_admin_rejects_a_path_that_contradicts_the_declared_one() -> None:
    declared = Starlette()
    declared.state.mount_path = "/ops"
    with pytest.raises(ValueError, match="/ops"):
        mount_admin(_app(), declared, path="/admin")
    mount_admin(_app(), declared, path="/ops")  # agreeing is fine


def test_public_routes_are_stored_as_route_objects() -> None:
    app = _app()
    mount_admin(app, _sub)
    public = getattr(app.state, mw.PUBLIC_ROUTES_ATTR)
    assert all(isinstance(route, BaseRoute) for route in public)
    assert any(route is app.router.routes[-1] for route in public)  # the admin mount


def test_mount_admin_rejects_bad_path() -> None:
    for bad in ("admin", "/", "/admin/", ""):
        with pytest.raises(ValueError, match="path"):
            mount_admin(_app(), _sub, path=bad)


# --- routes added after create_app never inherit an exemption -------------------------------


async def test_later_catch_all_router_is_protected() -> None:
    app = _app()
    late = APIRouter()

    @late.get("/{item}")
    async def item(item: str) -> str:
        return item

    app.include_router(late)
    assert _status(await _call(app, "/anything")) == 403
    assert _status(await _call(app, "/health/live")) == 200


async def test_later_admin_param_router_is_protected() -> None:
    app = _app()
    late = APIRouter()

    @late.get("/admin/{x}")
    async def admin_x(x: str) -> str:
        return x

    app.include_router(late)
    assert _status(await _call(app, "/admin/x")) == 403
    assert _status(await _call(app, "/admin/users")) == 403


async def test_later_add_api_route_under_admin_is_protected() -> None:
    app = _app()

    async def late() -> str:
        return "late"

    app.add_api_route("/admin/late", late, methods=["GET"])
    assert _status(await _call(app, "/admin/late")) == 403


async def test_later_mount_without_helper_is_protected() -> None:
    app = _app()
    app.mount("/admin", _sub)
    assert _status(await _call(app, "/admin/users")) == 403
    assert _status(await _call(app, "/admin/")) == 403


# --- websockets -----------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/ws", "/health/live", "/health/x", "/admin/x", "/anything"])
async def test_websocket_without_auth_is_closed_1008_even_if_route_added_later(path: str) -> None:
    app = _app()
    reached: list[str] = []

    async def handler(ws: WebSocket) -> None:
        reached.append("handler")
        await ws.accept()

    for pattern in ("/{x}", "/health/{x}", "/admin/{x}", "/ws"):
        app.add_api_websocket_route(pattern, handler)
    sent = await _call(app, path, kind="websocket")
    assert sent == [{"type": "websocket.close", "code": 1008}]
    assert reached == []


async def test_websocket_with_auth_reaches_handler() -> None:
    app = _app()
    reached: list[str] = []

    async def handler(ws: WebSocket) -> None:
        reached.append("handler")
        await ws.accept()
        await ws.close()

    app.add_api_websocket_route("/ws", handler)
    await _call(app, "/ws", kind="websocket", headers=AUTH)
    assert reached == ["handler"]


# --- root_path ------------------------------------------------------------------------------


async def test_root_path_is_honoured_for_public_decision() -> None:
    assert _status(await _call(_app(), "/api/health/live", root_path="/api")) == 200
    assert _status(await _call(_app(), "/api/admin-x", root_path="/api")) == 403
    assert _status(await _call(_app(), "/api/things", root_path="/api")) == 403
    assert _status(await _call(_app(), "/apix/health/live", root_path="/api")) == 403


# --- failures ---------------------------------------------------------------------------------


async def test_authenticate_crash_is_logged_500_without_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class _Log:
        def exception(self, event: str, **_: Any) -> None:
            events.append(event)

    class _Broken:
        async def authenticate(self, _request: Any) -> Any:
            raise RuntimeError("jwks fetch failed: https://idp/secret")

    monkeypatch.setattr(mw, "_log", _Log())
    sent = await _call(_app(auth=_Broken()), "/things")
    body = b"".join(m.get("body", b"") for m in sent)
    assert _status(sent) == 500
    assert b"secret" not in body
    assert b"internal_error" in body
    assert events == ["http.unhandled_exception"]


async def test_error_after_response_start_reraises_without_second_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class _Log:
        def exception(self, event: str, **_: Any) -> None:
            events.append(event)

    monkeypatch.setattr(mw, "_log", _Log())
    app = _app()
    sent: list[Message] = []

    inbox: list[Message] = [{"type": "http.request", "body": b"", "more_body": False}]

    async def receive() -> Message:
        if inbox:
            return inbox.pop(0)
        await asyncio.Event().wait()  # client stays connected; cancelled by the server
        raise AssertionError("unreachable")

    async def send(message: Message) -> None:
        sent.append(message)

    scope: Scope = {
        "type": "http",
        "path": "/stream",
        "root_path": "",
        "headers": AUTH,
        "query_string": b"",
        "method": "GET",
        "scheme": "http",
        "server": ("t", 80),
        "client": ("c", 1),
        "http_version": "1.1",
    }
    with pytest.raises(BaseException, match="late failure"):
        await app(scope, receive, send)
    assert [m["type"] for m in sent].count("http.response.start") == 1
    assert events == ["http.unhandled_exception"]
