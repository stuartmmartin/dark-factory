"""Authentication backends: turn a request into a RequestContext (A13)."""

from __future__ import annotations

import re
from typing import Literal, Protocol
from uuid import UUID, uuid4

from starlette.requests import HTTPConnection

from sb_kernel.context import RequestContext
from sb_kernel.errors import Forbidden

__all__ = ["AuthBackend", "AuthMode", "DevHeaderAuth", "backend_for", "safe_request_id"]

AuthMode = Literal["dev", "oidc"]

_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9._:-]{1,128}")
_ACTOR_RE = re.compile(r"[A-Za-z0-9._:@-]{1,128}")
# Environments where header-trusting dev auth may exist. Everything else (prod, staging,
# empty, typos) is refused: an allowlist, not a prod denylist.
_DEV_ENVIRONMENTS = frozenset({"local", "dev", "test", "ci"})


def safe_request_id(raw: str | None) -> str:
    """Accept a client id only if short and charset-limited (log-injection guard)."""
    if raw is not None and _REQUEST_ID_RE.fullmatch(raw):
        return raw
    return str(uuid4())


class AuthBackend(Protocol):
    async def authenticate(self, request: HTTPConnection) -> RequestContext: ...


class DevHeaderAuth:
    """Trusts X-Tenant-Id / X-Actor headers. Only constructible in allowlisted environments."""

    def __init__(self, environment: str) -> None:
        if environment.strip().lower() not in _DEV_ENVIRONMENTS:
            raise ValueError(
                f"dev auth is only allowed in {sorted(_DEV_ENVIRONMENTS)}, got {environment!r}"
            )

    async def authenticate(self, request: HTTPConnection) -> RequestContext:
        raw = request.headers.get("x-tenant-id")
        if raw is None:
            raise Forbidden("missing X-Tenant-Id")
        try:
            tenant_id = UUID(raw)
        except ValueError:
            raise Forbidden("invalid X-Tenant-Id") from None
        actor = request.headers.get("x-actor")
        if actor is None:
            actor = "dev"
        elif not _ACTOR_RE.fullmatch(actor):
            raise Forbidden("invalid X-Actor")
        return RequestContext(
            tenant_id=tenant_id,
            actor=actor,
            request_id=safe_request_id(request.headers.get("x-request-id")),
        )


def backend_for(mode: AuthMode, environment: str) -> AuthBackend:
    if mode == "dev":
        return DevHeaderAuth(environment)
    raise NotImplementedError("OIDC auth is specified separately")
