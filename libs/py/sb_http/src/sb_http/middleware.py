"""Pure-ASGI request-context middleware.

Not BaseHTTPMiddleware: that runs the app in a separate task, so the contextvar set here
would not reach route handlers. Here the downstream app runs inside `use_context` in the
same task, so handlers and tasks they spawn see it.

Authentication exemption is by route identity, decided per request. The middleware asks the
app's own router which route would serve the request (the first route that fully matches,
using the scope's real type, http or websocket, and Starlette's own `root_path` handling).
The request skips authentication only if that exact route object (compared with `is`, never by
`id()`, which a later object could reuse) was registered as public (`app.state.sb_public_routes`,
a list of the route objects themselves): the health routes, docs routes when exposed, and the mount
made by `mount_admin`. Everything else authenticates, including 404s, websocket routes,
routes or mounts added after `create_app`, and any path that merely looks like a public one.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from starlette.requests import HTTPConnection
from starlette.routing import BaseRoute, Match
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sb_http.auth import AuthBackend, safe_request_id
from sb_http.errors import problem
from sb_kernel.context import use_context
from sb_kernel.errors import Forbidden
from sb_obs.logging import get_logger

__all__ = ["PUBLIC_ROUTES_ATTR", "RequestContextMiddleware"]

_log = get_logger("sb_http.middleware")

PUBLIC_ROUTES_ATTR = "sb_public_routes"


def _first_full_match(routes: list[BaseRoute], scope: Scope) -> BaseRoute | None:
    for route in routes:
        if route.matches(scope)[0] == Match.FULL:
            return route
    return None


def _is_public(scope: Scope) -> bool:
    app: Any = scope.get("app")
    router: Any = getattr(app, "router", None)
    if router is None:
        return False
    public: list[BaseRoute] = getattr(app.state, PUBLIC_ROUTES_ATTR, [])
    routes: list[BaseRoute] = router.routes
    route = _first_full_match(routes, scope)
    if route is None and scope["type"] == "http":
        # Mirror the router's redirect_slashes: /admin -> /admin/ is a redirect, not content.
        path: str = scope["path"]
        alt = path[:-1] if path.endswith("/") else path + "/"
        route = _first_full_match(routes, {**scope, "path": alt})
    return route is not None and any(route is candidate for candidate in public)


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, auth: AuthBackend) -> None:
        self.app = app
        self.auth = auth

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        request = HTTPConnection(scope)
        request_id = safe_request_id(request.headers.get("x-request-id"))

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message["headers"] if k.lower() != b"x-request-id"]
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        if _is_public(scope):
            await self._run(scope, receive, send_with_id)
            return

        try:
            ctx = await self.auth.authenticate(request)
        except Forbidden as exc:
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
                return
            await problem(403, Forbidden.code, exc.message)(scope, receive, send_with_id)
            return
        except Exception as exc:
            await self._fail(exc, scope, receive, send_with_id, started=False)
            return
        ctx = replace(ctx, request_id=safe_request_id(ctx.request_id))
        request_id = ctx.request_id
        with use_context(ctx):
            await self._run(scope, receive, send_with_id)

    async def _run(self, scope: Scope, receive: Receive, send: Send) -> None:
        started = False

        async def tracking(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking)
        except Exception as exc:
            await self._fail(exc, scope, receive, send, started=started)

    async def _fail(
        self, exc: Exception, scope: Scope, receive: Receive, send: Send, *, started: bool
    ) -> None:
        """Log once through the redacting logger, then answer 500 with no internals.

        After the response has started we cannot send a second one: the exception is logged
        here and re-raised so the server aborts the connection (the server may log it again).
        """
        _log.exception("http.unhandled_exception", error_type=type(exc).__name__)
        if started:
            raise exc
        if scope["type"] != "http":
            raise exc
        await problem(500, "internal_error", "internal server error")(scope, receive, send)
