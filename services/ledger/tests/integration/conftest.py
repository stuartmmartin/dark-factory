"""The ledger app shared by the HTTP and admin integration tests, on the migrated `ledger_test`
database.

`environment` and `auth_mode` have no defaults (D1), so every setting is explicit here. httpx's
`ASGITransport` does not run the lifespan, so the `app` fixture disposes the engine itself.
"""

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from ledger.bootstrap import Container, build_api
from ledger.infrastructure.settings import Settings

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "pw"  # noqa: S105 - dev admin login of the test app


@pytest.fixture(scope="session")
def ledger_settings(ledger_db: str, ledger_migrator_url: str) -> Settings:
    return Settings(
        environment="test",
        auth_mode="dev",
        database_url=SecretStr(ledger_db),
        migrator_url=SecretStr(ledger_migrator_url),
        # Only `ledger.migrate` uses the admin (database-creating) URL; the API never does.
        admin_database_url=SecretStr(ledger_migrator_url),
        admin_username=ADMIN_USERNAME,
        admin_password=SecretStr(ADMIN_PASSWORD),
        admin_secret_key=SecretStr("k" * 32),
    )


@pytest.fixture(scope="session")
async def app(ledger_settings: Settings) -> AsyncIterator[FastAPI]:
    """One app (one engine) per test session (D14)."""
    api = build_api(ledger_settings)
    container: Container = api.state.container
    try:
        yield api
    finally:
        await container.engine.dispose()
