"""The ledger's HTTP API end to end: routes, problem+json errors, idempotency, tenancy (T9).

Every test asserts the status before the body. Racing duplicates (409) are covered by the
OpenAccount unit test and the idempotency store contract, not over HTTP.
"""

from collections.abc import Callable
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

ACCOUNT = {"name": "Operating cash", "currency": "USD"}
Headers = Callable[..., dict[str, str]]


async def test_open_then_get_returns_the_same_account(
    client: httpx.AsyncClient, as_tenant: Headers
) -> None:
    opened = await client.post("/v1/accounts", json=ACCOUNT, headers=as_tenant())
    assert opened.status_code == 201
    body = opened.json()
    assert body["name"] == "Operating cash"
    assert body["currency"] == "USD"
    assert set(body) == {"id", "name", "currency", "opened_at"}

    fetched = await client.get(f"/v1/accounts/{body['id']}", headers=as_tenant())
    assert fetched.status_code == 200
    assert fetched.json() == body


async def test_unknown_account_is_404(client: httpx.AsyncClient, as_tenant: Headers) -> None:
    response = await client.get(f"/v1/accounts/{uuid4()}", headers=as_tenant())
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_another_tenants_account_is_404_not_403(
    client: httpx.AsyncClient, as_tenant: Headers
) -> None:
    opened = await client.post("/v1/accounts", json=ACCOUNT, headers=as_tenant())
    assert opened.status_code == 201
    account_id = opened.json()["id"]

    response = await client.get(f"/v1/accounts/{account_id}", headers=as_tenant(uuid4()))
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_missing_tenant_header_is_403(client: httpx.AsyncClient) -> None:
    response = await client.post("/v1/accounts", json=ACCOUNT)
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "Operating cash", "currency": "ZZZ"},
        {"name": "   ", "currency": "USD"},
    ],
    ids=["unsupported-currency", "blank-name"],
)
async def test_invalid_account_is_422_validation_failed(
    client: httpx.AsyncClient, as_tenant: Headers, payload: dict[str, str]
) -> None:
    response = await client.post("/v1/accounts", json=payload, headers=as_tenant())
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "validation_failed"


async def test_extra_body_field_is_422(client: httpx.AsyncClient, as_tenant: Headers) -> None:
    response = await client.post(
        "/v1/accounts", json={**ACCOUNT, "id": str(uuid4())}, headers=as_tenant()
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"


async def test_replayed_idempotency_key_returns_the_original_account(
    client: httpx.AsyncClient, as_tenant: Headers
) -> None:
    headers = as_tenant(**{"Idempotency-Key": f"open-{uuid4()}"})
    first = await client.post("/v1/accounts", json=ACCOUNT, headers=headers)
    assert first.status_code == 201

    replay = await client.post("/v1/accounts", json=ACCOUNT, headers=headers)
    assert replay.status_code == 200
    assert replay.json() == first.json()


async def test_reused_idempotency_key_with_a_different_body_is_422(
    client: httpx.AsyncClient, as_tenant: Headers
) -> None:
    headers = as_tenant(**{"Idempotency-Key": f"open-{uuid4()}"})
    first = await client.post("/v1/accounts", json=ACCOUNT, headers=headers)
    assert first.status_code == 201

    other = await client.post("/v1/accounts", json={**ACCOUNT, "name": "Payroll"}, headers=headers)
    assert other.status_code == 422
    assert other.json()["code"] == "idempotency_key_reused"


@pytest.mark.parametrize("key", ["has space", "k" * 201], ids=["space", "201-chars"])
async def test_malformed_idempotency_key_is_422(
    client: httpx.AsyncClient, as_tenant: Headers, key: str
) -> None:
    response = await client.post(
        "/v1/accounts", json=ACCOUNT, headers=as_tenant(**{"Idempotency-Key": key})
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"


def test_operation_ids_are_the_committed_contract(app: FastAPI) -> None:
    operation_ids = {
        operation["operationId"]
        for methods in app.openapi()["paths"].values()
        for operation in methods.values()
    }
    assert operation_ids == {
        "open_account",
        "get_account",
        "list_accounts",
        "get_account_balance",
        "post_journal_entry",
        "live",
        "ready",
    }


async def test_docs_are_served_outside_prod(client: httpx.AsyncClient) -> None:
    response = await client.get("/docs")
    assert response.status_code == 200


async def test_ready_checks_the_database(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/ready")
    assert response.status_code == 200
