"""Session-scoped real Postgres for integration tests (T5), with the compose roles.

The container gets the same roles as `compose/postgres/init/01-roles.sh` (a unit test keeps
the CREATE ROLE statements identical): `sb_migrator` (LOGIN CREATEDB BYPASSRLS), `sb_app`
(NOBYPASSRLS, the runtime role) and `sb_readonly`. As in a deployment, the database is owned by
`sb_migrator` (so it may create tables in `public`), and `sb_app` only has `USAGE` on `public`:
tests grant table privileges explicitly, the way a migration would.

Fixtures: `postgres_url` (the `sb_admin` superuser), `postgres_migrator_url`, `postgres_app_url`.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from testcontainers.community.postgres import PostgresContainer

IMAGE = "postgres:17-alpine"
DATABASE = "sb_test"
ADMIN_PASSWORD = "sb_admin"  # noqa: S105 - throwaway test container credential
MIGRATOR_PASSWORD = "sb_migrator"  # noqa: S105 - throwaway test container credential
APP_PASSWORD = "sb_app"  # noqa: S105 - throwaway test container credential
READONLY_PASSWORD = "sb_readonly"  # noqa: S105 - throwaway test container credential
# Same CREATE ROLE statements as compose/postgres/init/01-roles.sh (checked by a unit test).
ROLE_SQL_TEMPLATE = (
    "CREATE ROLE sb_migrator LOGIN CREATEDB BYPASSRLS PASSWORD '{migrator}';"
    "CREATE ROLE sb_app LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '{app}';"
    "CREATE ROLE sb_readonly LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '{readonly}';"
)
# What a deployment gives: the migrator owns the service database; the app may use `public`.
_DEPLOYMENT_SQL = (
    f"ALTER DATABASE {DATABASE} OWNER TO sb_migrator;GRANT USAGE ON SCHEMA public TO sb_app;"
)


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    with PostgresContainer(
        IMAGE,
        username="sb_admin",
        password=ADMIN_PASSWORD,
        dbname=DATABASE,
        driver="asyncpg",
    ) as container:
        sql = (
            ROLE_SQL_TEMPLATE.format(
                migrator=MIGRATOR_PASSWORD, app=APP_PASSWORD, readonly=READONLY_PASSWORD
            )
            + _DEPLOYMENT_SQL
        )
        result = container.exec(["psql", "-U", "sb_admin", "-d", DATABASE, "-c", sql])
        if result.exit_code != 0:
            raise RuntimeError(f"role bootstrap failed: {result.output!r}")
        yield container


@pytest.fixture(scope="session")
def postgres_url(postgres_container: PostgresContainer) -> str:
    return postgres_container.get_connection_url()


def _role_url(container: PostgresContainer, role: str, password: str) -> str:
    host, port = container.get_container_host_ip(), container.get_exposed_port(5432)
    return f"postgresql+asyncpg://{role}:{password}@{host}:{port}/{DATABASE}"


@pytest.fixture(scope="session")
def postgres_migrator_url(postgres_container: PostgresContainer) -> str:
    return _role_url(postgres_container, "sb_migrator", MIGRATOR_PASSWORD)


@pytest.fixture(scope="session")
def postgres_app_url(postgres_container: PostgresContainer) -> str:
    return _role_url(postgres_container, "sb_app", APP_PASSWORD)
