from __future__ import annotations

import asyncio
from typing import Any

import pytest
from structlog.testing import capture_logs

from sb_http.app import create_app
from sb_http.auth import DevHeaderAuth


async def _ok() -> bool:
    return True


async def _down() -> bool:
    return False


async def _raises() -> bool:
    raise ConnectionError("db unreachable at postgres://u:pw@h/db")


async def test_live_is_200(client_for: Any) -> None:
    async with client_for() as client:
        resp = await client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_ready_200_when_checks_pass(client_for: Any) -> None:
    async with client_for(readiness=(_ok, _ok)) as client:
        resp = await client.get("/health/ready")
    assert resp.status_code == 200


async def test_ready_200_with_no_checks(client_for: Any) -> None:
    async with client_for() as client:
        resp = await client.get("/health/ready")
    assert resp.status_code == 200


async def test_ready_503_when_check_false(client_for: Any) -> None:
    async with client_for(readiness=(_ok, _down)) as client:
        resp = await client.get("/health/ready")
    assert resp.status_code == 503


async def test_ready_503_when_check_raises_without_leaking(client_for: Any) -> None:
    async with client_for(readiness=(_raises,)) as client:
        resp = await client.get("/health/ready")
    assert resp.status_code == 503
    assert "postgres" not in resp.text


async def _hangs() -> bool:
    await asyncio.Event().wait()  # never set: a check stuck on a dead dependency
    return True


async def test_ready_503_when_a_check_exceeds_its_timeout(client_for: Any) -> None:
    with capture_logs() as logs:
        async with (
            asyncio.timeout(5),
            client_for(readiness=(_ok, _hangs), readiness_timeout=0.05) as client,
        ):
            resp = await client.get("/health/ready")
    assert resp.status_code == 503
    [failed] = [e for e in logs if e["event"] == "http.readiness_check_failed"]
    assert failed["error_type"] == "TimeoutError"


async def test_raising_check_is_logged_with_a_module_prefixed_event(client_for: Any) -> None:
    with capture_logs() as logs:
        async with client_for(readiness=(_raises,)) as client:
            await client.get("/health/ready")
    assert [e["event"] for e in logs] == ["http.readiness_check_failed"]


def test_readiness_timeout_must_be_positive() -> None:
    with pytest.raises(ValueError, match="readiness_timeout"):
        create_app(
            title="t", version="0", routers=[], auth=DevHeaderAuth("test"), readiness_timeout=0
        )
