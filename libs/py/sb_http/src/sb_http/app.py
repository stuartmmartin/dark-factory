"""FastAPI application factory."""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from starlette.routing import BaseRoute, Match
from starlette.types import ASGIApp, Lifespan, Scope

from sb_http.auth import AuthBackend
from sb_http.errors import install_error_handlers
from sb_http.health import DEFAULT_READINESS_TIMEOUT_SECONDS, health_router
from sb_http.middleware import PUBLIC_ROUTES_ATTR, RequestContextMiddleware

__all__ = ["MOUNT_PATH_STATE", "create_app", "mount_admin"]

_DOCS_PATHS = ("/docs", "/docs/oauth2-redirect", "/openapi.json")
_ADMIN_PATH_OK = re.compile(r"/[^/]+(/[^/]+)*")


def _unique_id(route: APIRoute) -> str:
    return route.name


def _assert_no_public_collisions(routers: Sequence[APIRouter], probes: Sequence[str]) -> None:
    """Early developer error: a user route that would shadow a public path.

    Not the security boundary. Exemption is by route identity (see middleware), so a
    colliding route is never exempt from auth; this only reports the mistake at build time.
    """
    scratch = FastAPI(docs_url=None, openapi_url=None, redoc_url=None)
    for router in routers:
        scratch.include_router(router)
    for kind in ("http", "websocket"):
        for probe in probes:
            scope: Scope = {
                "type": kind,
                "method": "GET",
                "path": probe,
                "root_path": "",
                "headers": [],
                "query_string": b"",
            }
            if any(route.matches(scope)[0] != Match.NONE for route in scratch.router.routes):
                raise ValueError(
                    f"a {kind} route can match public path {probe!r}; it would shadow it"
                )


def _assert_unique_operation_ids(app: FastAPI) -> None:
    seen: set[str] = set()
    app.openapi_schema = None  # never trust a cached schema: routes may have been added
    schema = app.openapi()
    app.openapi_schema = None  # let the served schema regenerate with any late routes
    for methods in schema.get("paths", {}).values():
        for op in methods.values():
            op_id = op.get("operationId")
            if op_id is None:
                continue
            if op_id in seen:
                raise ValueError(f"duplicate OpenAPI operation id {op_id!r}")
            seen.add(op_id)


MOUNT_PATH_STATE = "mount_path"  # sb_admin.create_admin records its mount path here
_DEFAULT_ADMIN_PATH = "/admin"


def _declared_mount_path(asgi_app: ASGIApp) -> str | None:
    declared = getattr(getattr(asgi_app, "state", None), MOUNT_PATH_STATE, None)
    return declared if isinstance(declared, str) else None


def mount_admin(app: FastAPI, asgi_app: ASGIApp, path: str | None = None) -> None:
    """Mount a self-authenticating app (e.g. SQLAdmin) as the one public mount.

    The mounted app skips sb_http authentication entirely, so it must carry its own.
    The path is the one the app declares (`app.state.mount_path`, which
    `sb_admin.create_admin` sets, so its session cookie path matches), else `path`, else
    `/admin`. A `path` that contradicts the declared one is a `ValueError`.
    """
    declared = _declared_mount_path(asgi_app)
    if declared is not None and path is not None and path != declared:
        raise ValueError(f"path {path!r} contradicts the admin app's mount path {declared!r}")
    where = declared if declared is not None else path if path is not None else _DEFAULT_ADMIN_PATH
    if not _ADMIN_PATH_OK.fullmatch(where):
        raise ValueError(f"path must start with '/' and not end with '/', got {where!r}")
    app.mount(where, asgi_app)
    public: list[BaseRoute] = getattr(app.state, PUBLIC_ROUTES_ATTR)
    public.append(app.router.routes[-1])


def create_app(
    *,
    title: str,
    version: str,
    routers: Sequence[APIRouter],
    auth: AuthBackend,
    readiness: Sequence[Callable[[], Awaitable[bool]]] = (),
    readiness_timeout: float = DEFAULT_READINESS_TIMEOUT_SECONDS,
    lifespan: Lifespan[FastAPI] | None = None,
    expose_docs: bool = False,
) -> FastAPI:
    """Build the service app. Each readiness check gets `readiness_timeout` seconds; a check
    that times out counts as not ready (C6)."""
    if readiness_timeout <= 0:
        raise ValueError("readiness_timeout must be positive")
    probes = ["/health/live", "/health/ready", *(_DOCS_PATHS if expose_docs else ())]
    _assert_no_public_collisions(routers, [*probes, "/admin", "/admin/x", "/admin/x/y"])

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
        _assert_unique_operation_ids(app)  # covers routes added after create_app
        if lifespan is None:
            yield
        else:
            async with lifespan(app):
                yield

    app = FastAPI(
        title=title,
        version=version,
        lifespan=_lifespan,
        generate_unique_id_function=_unique_id,
        docs_url="/docs" if expose_docs else None,
        openapi_url="/openapi.json" if expose_docs else None,
        redoc_url=None,
    )
    # Public routes: what FastAPI registered for docs (if any), then the health routes.
    public: list[BaseRoute] = list(app.router.routes)
    install_error_handlers(app)
    for hr in health_router(readiness, timeout=readiness_timeout).routes:
        if isinstance(hr, APIRoute):
            app.add_api_route(hr.path, hr.endpoint, methods=sorted(hr.methods or ()), name=hr.name)
            public.append(app.router.routes[-1])
    setattr(app.state, PUBLIC_ROUTES_ATTR, public)
    for router in routers:
        app.include_router(router)
    _assert_unique_operation_ids(app)
    app.add_middleware(RequestContextMiddleware, auth=auth)
    return app
