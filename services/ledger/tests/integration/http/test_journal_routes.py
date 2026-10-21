"""Double-entry over HTTP: list accounts, post entries, read balances (T9).

Every test asserts the status before the body, and runs as a fresh tenant.
"""

from collections.abc import Callable
from uuid import uuid4

import httpx
import pytest

Headers = Callable[..., dict[str, str]]


async def _open(client: httpx.AsyncClient, headers: dict[str, str], name: str, ccy="USD") -> str:
    response = await client.post(
        "/v1/accounts", json={"name": name, "currency": ccy}, headers=headers
    )
    assert response.status_code == 201
    return response.json()["id"]


def _entry(debit: str, credit: str, amount: str, description: str = "Transfer") -> dict:
    return {
        "description": description,
        "lines": [
            {"account_id": debit, "side": "debit", "amount": amount},
            {"account_id": credit, "side": "credit", "amount": amount},
        ],
    }


async def test_list_returns_the_tenants_accounts_oldest_first(
    client: httpx.AsyncClient, as_tenant: Headers
) -> None:
    first = await _open(client, as_tenant(), "Cash")
    second = await _open(client, as_tenant(), "Equity")
    await _open(client, as_tenant(uuid4()), "Someone else's")

    response = await client.get("/v1/accounts", headers=as_tenant())
    assert response.status_code == 200
    assert [a["id"] for a in response.json()["items"]] == [first, second]

    limited = await client.get("/v1/accounts", params={"limit": 1}, headers=as_tenant())
    assert limited.status_code == 200
    assert [a["id"] for a in limited.json()["items"]] == [first]


@pytest.mark.parametrize("limit", [0, 201, "many"])
async def test_a_bad_limit_is_422(client: httpx.AsyncClient, as_tenant: Headers, limit) -> None:
    response = await client.get("/v1/accounts", params={"limit": limit}, headers=as_tenant())
    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"


async def test_posting_an_entry_moves_both_balances(
    client: httpx.AsyncClient, as_tenant: Headers
) -> None:
    cash = await _open(client, as_tenant(), "Cash")
    equity = await _open(client, as_tenant(), "Equity")

    posted = await client.post(
        "/v1/journal-entries", json=_entry(cash, equity, "1000.00"), headers=as_tenant()
    )
    assert posted.status_code == 201
    body = posted.json()
    assert set(body) == {"id", "description", "currency", "posted_at", "lines"}
    assert body["currency"] == "USD"
    assert body["lines"] == [
        {"account_id": cash, "side": "debit", "amount": "1000.00"},
        {"account_id": equity, "side": "credit", "amount": "1000.00"},
    ]
    second = await client.post(
        "/v1/journal-entries", json=_entry(equity, cash, "250.5"), headers=as_tenant()
    )
    assert second.status_code == 201

    balance = await client.get(f"/v1/accounts/{cash}/balance", headers=as_tenant())
    assert balance.status_code == 200
    assert balance.json() == {
        "account_id": cash,
        "currency": "USD",
        "debits": "1000.00",
        "credits": "250.50",
        "balance": "749.50",
    }
    other = await client.get(f"/v1/accounts/{equity}/balance", headers=as_tenant())
    assert other.status_code == 200
    assert other.json()["balance"] == "-749.50"


async def test_a_replayed_idempotency_key_returns_the_original_entry_once(
    client: httpx.AsyncClient, as_tenant: Headers
) -> None:
    cash = await _open(client, as_tenant(), "Cash")
    equity = await _open(client, as_tenant(), "Equity")
    headers = as_tenant(**{"Idempotency-Key": "entry-1"})

    first = await client.post(
        "/v1/journal-entries", json=_entry(cash, equity, "5"), headers=headers
    )
    again = await client.post(
        "/v1/journal-entries", json=_entry(cash, equity, "5"), headers=headers
    )
    assert first.status_code == 201
    assert again.status_code == 200
    assert again.json() == first.json()

    balance = await client.get(f"/v1/accounts/{cash}/balance", headers=as_tenant())
    assert balance.json()["debits"] == "5.00"


@pytest.mark.parametrize(
    ("amounts", "code"),
    [
        (("100.00", "99.00"), "validation_failed"),
        (("1.005", "1.005"), "validation_failed"),
        (("-1.00", "-1.00"), "validation_failed"),
        (("1e3", "1e3"), "validation_failed"),
    ],
    ids=["unbalanced", "excess-precision", "negative", "not-a-decimal-string"],
)
async def test_an_invalid_entry_is_422_and_changes_nothing(
    client: httpx.AsyncClient, as_tenant: Headers, amounts: tuple[str, str], code: str
) -> None:
    cash = await _open(client, as_tenant(), "Cash")
    equity = await _open(client, as_tenant(), "Equity")
    entry = _entry(cash, equity, amounts[0])
    entry["lines"][1]["amount"] = amounts[1]

    response = await client.post("/v1/journal-entries", json=entry, headers=as_tenant())
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == code

    balance = await client.get(f"/v1/accounts/{cash}/balance", headers=as_tenant())
    assert balance.json()["debits"] == "0.00"


async def test_mixing_currencies_is_422(client: httpx.AsyncClient, as_tenant: Headers) -> None:
    dollars = await _open(client, as_tenant(), "Cash")
    euros = await _open(client, as_tenant(), "Euro cash", ccy="EUR")
    response = await client.post(
        "/v1/journal-entries", json=_entry(dollars, euros, "1.00"), headers=as_tenant()
    )
    assert response.status_code == 422
    assert response.json()["code"] == "currency_mismatch"


async def test_another_tenants_account_is_404_for_entries_and_balances(
    client: httpx.AsyncClient, as_tenant: Headers
) -> None:
    mine = await _open(client, as_tenant(), "Cash")
    theirs = await _open(client, as_tenant(uuid4()), "Their cash")

    posted = await client.post(
        "/v1/journal-entries", json=_entry(mine, theirs, "1.00"), headers=as_tenant()
    )
    assert posted.status_code == 404
    assert posted.json()["code"] == "not_found"
    balance = await client.get(f"/v1/accounts/{theirs}/balance", headers=as_tenant())
    assert balance.status_code == 404


async def test_too_many_lines_is_422_at_the_transport(
    client: httpx.AsyncClient, as_tenant: Headers
) -> None:
    line = {"account_id": str(uuid4()), "side": "debit", "amount": "1.00"}
    response = await client.post(
        "/v1/journal-entries",
        json={"description": "Huge", "lines": [line] * 101},
        headers=as_tenant(),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"


async def test_missing_tenant_header_is_403(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/accounts")
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
