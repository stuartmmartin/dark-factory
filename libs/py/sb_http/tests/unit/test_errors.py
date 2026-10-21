from __future__ import annotations

from typing import Any

import pytest
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import sb_http.middleware as mw
from sb_http.errors import problem
from sb_kernel.errors import (
    Conflict,
    CurrencyMismatch,
    DomainError,
    Forbidden,
    IdempotencyKeyReused,
    NotFound,
    ValidationFailed,
)

TENANT = {"X-Tenant-Id": "11111111-1111-1111-1111-111111111111"}


class Body(BaseModel):
    n: int


def _router() -> APIRouter:
    r = APIRouter()

    @r.get("/nf")
    async def nf() -> None:
        raise NotFound("thing missing")

    @r.get("/conflict")
    async def conflict() -> None:
        raise Conflict("already there")

    @r.get("/invalid")
    async def invalid() -> None:
        raise ValidationFailed("bad input")

    @r.get("/forbidden")
    async def forbidden() -> None:
        raise Forbidden("nope")

    @r.get("/domain")
    async def domain() -> None:
        raise DomainError("generic")

    @r.get("/currency")
    async def currency() -> None:
        raise CurrencyMismatch("USD vs EUR")

    @r.get("/reused")
    async def reused() -> None:
        raise IdempotencyKeyReused("idempotency key already used for a different request")

    @r.post("/body")
    async def body(b: Body) -> Body:
        return b

    @r.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail postgres://u:pw@host/db")

    return r


@pytest.mark.parametrize(
    ("path", "status", "code"),
    [
        ("/nf", 404, "not_found"),
        ("/conflict", 409, "conflict"),
        ("/invalid", 422, "validation_failed"),
        ("/forbidden", 403, "forbidden"),
        ("/domain", 400, "domain_error"),
        ("/currency", 422, "currency_mismatch"),
        ("/reused", 422, "idempotency_key_reused"),
    ],
)
async def test_domain_errors_map_to_problem_json(
    client_for: Any, path: str, status: int, code: str
) -> None:
    async with client_for(_router()) as client:
        resp = await client.get(path, headers=TENANT)
    assert resp.status_code == status
    assert resp.headers["content-type"].startswith("application/problem+json")
    body: dict[str, Any] = resp.json()
    assert body["code"] == code
    assert body["status"] == status
    assert body["type"] == "about:blank"
    assert isinstance(body["title"], str)
    assert isinstance(body["detail"], str)


async def test_fastapi_request_validation_maps_to_problem_422(client_for: Any) -> None:
    async with client_for(_router()) as client:
        resp = await client.post("/body", headers=TENANT, json={"n": "not-int"})
    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("application/problem+json")
    body: dict[str, Any] = resp.json()
    assert body["code"] == "validation_failed"
    assert body["status"] == 422
    assert "not-int" not in body["detail"]


async def test_unknown_route_is_problem_json_404(client_for: Any) -> None:
    async with client_for(_router()) as client:
        resp = await client.get("/nope", headers=TENANT)
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["code"] == "not_found"


async def test_unhandled_exception_is_500_without_internal_details(client_for: Any) -> None:
    async with client_for(_router(), raise_app_exceptions=False) as client:
        resp = await client.get("/boom", headers=TENANT)
    assert resp.status_code == 500
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["code"] == "internal_error"
    assert "secret" not in resp.text
    assert "postgres" not in resp.text


async def test_unhandled_exception_is_logged_through_sb_obs(
    client_for: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    class _Log:
        def exception(self, event: str, **kw: Any) -> None:
            calls.append((event, kw))

    monkeypatch.setattr(mw, "_log", _Log())
    async with client_for(_router(), raise_app_exceptions=False) as client:
        resp = await client.get("/boom", headers=TENANT)
    assert resp.status_code == 500
    assert [c[0] for c in calls] == ["http.unhandled_exception"]


def test_problem_builds_response() -> None:
    resp = problem(409, "conflict", "dup")
    assert resp.status_code == 409
    assert resp.media_type == "application/problem+json"
    assert b'"title":"Conflict"' in resp.body


class _Items(BaseModel):
    items: list[int]


async def test_405_maps_to_problem_json(client_for: Any) -> None:
    async with client_for(_router()) as client:
        resp = await client.get("/body", headers=TENANT)
    assert resp.status_code == 405
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["code"] == "method_not_allowed"
    assert "POST" in resp.headers["allow"]


async def test_http_exception_dict_detail_is_json_not_repr(client_for: Any) -> None:
    r = APIRouter()

    @r.get("/teapot")
    async def teapot() -> None:
        raise HTTPException(status_code=418, detail={"why": "short", "n": 1})

    async with client_for(r) as client:
        resp = await client.get("/teapot", headers=TENANT)
    assert resp.status_code == 418
    assert resp.json()["detail"] == '{"why": "short", "n": 1}'


async def test_validation_detail_is_capped(client_for: Any) -> None:
    r = APIRouter()

    @r.post("/items")
    async def items(b: _Items) -> None: ...

    async with client_for(r) as client:
        resp = await client.post("/items", headers=TENANT, json={"items": ["x"] * 500})
    assert resp.status_code == 422
    detail: str = resp.json()["detail"]
    assert len(detail) <= 2000
    assert len(detail.split("; ")) <= 20
