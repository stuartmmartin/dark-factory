"""Who is acting, for which tenant: set by the interface layer, read by adapters (A13)."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID

from sb_kernel.errors import Forbidden


@dataclass(frozen=True)
class RequestContext:
    tenant_id: UUID
    actor: str
    request_id: str
    trace_id: str | None = None


_current: ContextVar[RequestContext | None] = ContextVar("sb_request_context", default=None)


def optional_context() -> RequestContext | None:
    return _current.get()


def current_context() -> RequestContext:
    ctx = _current.get()
    if ctx is None:
        raise Forbidden("no request context")
    return ctx


@contextmanager
def use_context(ctx: RequestContext) -> Generator[RequestContext]:
    token = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)
