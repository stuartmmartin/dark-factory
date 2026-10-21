from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from sb_http.idempotency import idempotency_key, request_hash

TENANT = {"X-Tenant-Id": "11111111-1111-1111-1111-111111111111"}


def _router() -> APIRouter:
    r = APIRouter()

    @r.post("/things")
    async def create(key: Annotated[str | None, Depends(idempotency_key)]) -> dict[str, str | None]:
        return {"key": key}

    return r


async def test_valid_key_passes_through(client_for: Any) -> None:
    async with client_for(_router()) as client:
        resp = await client.post("/things", headers={**TENANT, "Idempotency-Key": "abc-123_A.b:c"})
    assert resp.status_code == 200
    assert resp.json() == {"key": "abc-123_A.b:c"}


async def test_absent_key_is_none(client_for: Any) -> None:
    async with client_for(_router()) as client:
        resp = await client.post("/things", headers=TENANT)
    assert resp.status_code == 200
    assert resp.json() == {"key": None}


async def test_key_of_200_chars_accepted(client_for: Any) -> None:
    async with client_for(_router()) as client:
        resp = await client.post("/things", headers={**TENANT, "Idempotency-Key": "k" * 200})
    assert resp.status_code == 200


async def test_key_of_201_chars_rejected(client_for: Any) -> None:
    async with client_for(_router()) as client:
        resp = await client.post("/things", headers={**TENANT, "Idempotency-Key": "k" * 201})
    assert resp.status_code == 422
    assert resp.json()["code"] == "validation_failed"


async def test_key_with_space_rejected(client_for: Any) -> None:
    async with client_for(_router()) as client:
        resp = await client.post("/things", headers={**TENANT, "Idempotency-Key": "has space"})
    assert resp.status_code == 422


async def test_empty_key_rejected(client_for: Any) -> None:
    async with client_for(_router()) as client:
        resp = await client.post("/things", headers={**TENANT, "Idempotency-Key": ""})
    assert resp.status_code == 422


class _AB(BaseModel):
    a: int
    b: str


class _BA(BaseModel):
    b: str
    a: int


def test_request_hash_stable_across_field_order() -> None:
    assert request_hash(_AB(a=1, b="x")) == request_hash(_BA(b="x", a=1))


def test_request_hash_differs_on_content() -> None:
    assert request_hash(_AB(a=1, b="x")) != request_hash(_AB(a=2, b="x"))
    assert len(request_hash(_AB(a=1, b="x"))) == 64


class _Tags(BaseModel):
    tags: set[str]


class _TagList(BaseModel):
    tags: list[str]


class _Amount(BaseModel):
    amount: Decimal


def test_request_hash_normalises_sets() -> None:
    assert request_hash(_Tags(tags={"b", "a", "c"})) == request_hash(_TagList(tags=["a", "b", "c"]))


def test_request_hash_decimal_representation_is_significant() -> None:
    assert request_hash(_Amount(amount=Decimal("1.1"))) != request_hash(
        _Amount(amount=Decimal("1.10"))
    )
    assert request_hash(_Amount(amount=Decimal("1.10"))) == request_hash(
        _Amount(amount=Decimal("1.10"))
    )
