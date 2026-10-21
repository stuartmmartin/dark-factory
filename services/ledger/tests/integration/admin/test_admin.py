"""The ledger admin: one read-only view, three acceptors, dev login, never in prod.

D9 (RULING, flagged for a human): the admin runs on the `sb_app` engine with no tenant set, so
FORCE RLS hides every tenant's rows from its list views. The list test pins that.
"""

from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from ledger.application.dto import GetAccountQuery, OpenAccountCommand
from ledger.bootstrap import Container, build_api
from ledger.infrastructure.settings import Settings
from ledger.interface.admin.views import AccountAdmin
from sb_kernel.context import RequestContext, use_context

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "pw"  # noqa: S105 - matches ../conftest.py


@pytest.fixture
async def admin(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """A client logged in to the admin."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://ledger") as c:
        login = await c.post(
            "/admin/login", data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
        )
        assert login.status_code == 302
        yield c


async def test_account_list_is_200_and_rls_hides_tenant_rows(
    app: FastAPI, admin: httpx.AsyncClient
) -> None:
    container: Container = app.state.container
    tenant = RequestContext(tenant_id=uuid4(), actor="tester", request_id="req-admin")
    with use_context(tenant):
        account = await container.open_account(
            OpenAccountCommand(name="Operating cash", currency="USD")
        )
        # The row is committed and visible to its own tenant, so its absence below is RLS.
        assert await container.get_account(GetAccountQuery(account_id=account.id)) == account

    response = await admin.get(f"/admin/{AccountAdmin.identity}/list")
    assert response.status_code == 200
    assert "Accounts" in response.text  # the list page itself, not a login redirect
    assert str(account.id) not in response.text  # D9: no tenant set, so RLS shows zero rows


async def test_accounts_cannot_be_created_from_the_admin(admin: httpx.AsyncClient) -> None:
    response = await admin.get(f"/admin/{AccountAdmin.identity}/create")
    assert response.status_code in {403, 404}


async def test_allocation_acceptor_splits_the_total(admin: httpx.AsyncClient) -> None:
    response = await admin.post(
        "/admin/acceptors/allocation", data={"total": "100.00", "weights": "1,1,2"}
    )
    assert response.status_code == 200
    assert "50.00" in response.text
    assert "25.00" in response.text


async def test_allocation_acceptor_shows_the_policy_error(admin: httpx.AsyncClient) -> None:
    response = await admin.post(
        "/admin/acceptors/allocation", data={"total": "100.00", "weights": "0"}
    )
    assert response.status_code == 422
    assert "weights must sum to more than zero" in response.text


async def test_journal_entry_acceptor_totals_a_balanced_entry(admin: httpx.AsyncClient) -> None:
    response = await admin.post(
        "/admin/acceptors/journal-entry",
        data={"currency": "USD", "lines": "debit 60.00, debit 40, credit 100.00"},
    )
    assert response.status_code == 200
    assert "100.00" in response.text


async def test_journal_entry_acceptor_shows_an_unbalanced_entry(
    admin: httpx.AsyncClient,
) -> None:
    response = await admin.post(
        "/admin/acceptors/journal-entry",
        data={"currency": "USD", "lines": "debit 10.00, credit 9.00"},
    )
    assert response.status_code == 422
    assert "entry does not balance" in response.text


async def test_transfer_acceptor_shows_the_two_lines(admin: httpx.AsyncClient) -> None:
    response = await admin.post(
        "/admin/acceptors/transfer",
        data={"amount": "1500", "from_account": "Operating cash", "to_account": "Savings"},
    )
    assert response.status_code == 200
    assert "1500.00 Savings" in response.text
    assert "1500.00 Operating cash" in response.text


async def test_transfer_acceptor_shows_the_policy_error(admin: httpx.AsyncClient) -> None:
    response = await admin.post(
        "/admin/acceptors/transfer",
        data={"amount": "10.005", "from_account": "Savings", "to_account": "Rent"},
    )
    assert response.status_code == 422
    assert "more precision than USD allows" in response.text


async def test_transfer_acceptor_rerenders_the_form_on_missing_input(
    admin: httpx.AsyncClient,
) -> None:
    response = await admin.post("/admin/acceptors/transfer", data={"amount": "1.00"})
    assert response.status_code == 422
    assert "from_account: Field required" in response.text


def test_prod_does_not_start_until_oidc_exists() -> None:
    """D1: prod uses OIDC, which `backend_for` does not implement, so the app (and with it the
    admin) cannot be built in prod."""
    prod = Settings(
        environment="prod",
        auth_mode="oidc",
        database_url=SecretStr("postgresql+asyncpg://sb_app:x@db/ledger"),
        migrator_url=SecretStr("postgresql+asyncpg://sb_migrator:x@db/ledger"),
        admin_database_url=SecretStr("postgresql+asyncpg://postgres:x@db/postgres"),
    )
    with pytest.raises(NotImplementedError):
        build_api(prod)
