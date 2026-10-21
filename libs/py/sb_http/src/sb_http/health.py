"""Liveness and readiness routes. Each readiness check is bounded by a timeout (C6)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from sb_obs.logging import get_logger

__all__ = ["DEFAULT_READINESS_TIMEOUT_SECONDS", "health_router"]

DEFAULT_READINESS_TIMEOUT_SECONDS = 2.0

_log = get_logger("sb_http.health")


def health_router(
    readiness: Sequence[Callable[[], Awaitable[bool]]],
    *,
    timeout: float = DEFAULT_READINESS_TIMEOUT_SECONDS,
) -> APIRouter:
    router = APIRouter(prefix="/health", tags=["health"])

    @router.get("/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/ready")
    async def ready() -> JSONResponse:
        for check in readiness:
            try:
                async with asyncio.timeout(timeout):  # a hung check is not ready
                    ok = await check()
            except Exception as exc:  # TimeoutError included
                _log.warning("http.readiness_check_failed", error_type=type(exc).__name__)
                ok = False
            if not ok:
                return JSONResponse(status_code=503, content={"status": "unavailable"})
        return JSONResponse(status_code=200, content={"status": "ok"})

    return router
