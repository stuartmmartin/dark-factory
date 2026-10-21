"""`ledger.migrate` refuses to run without its privileged URLs, before any I/O (M4)."""

import pytest
from pydantic import SecretStr

from ledger.infrastructure.settings import Settings
from ledger.migrate import MigrationSettingsError, migrate

APP_ONLY = Settings(
    environment="test",
    auth_mode="dev",
    database_url=SecretStr("postgresql+asyncpg://sb_app:x@unreachable.invalid/ledger"),
)  # no admin credentials: only the API process receives them


@pytest.mark.parametrize(
    ("present", "missing_env"),
    [
        ({"admin_database_url": SecretStr("postgresql+asyncpg://a:x@h/p")}, "LEDGER_MIGRATOR_URL"),
        ({"migrator_url": SecretStr("postgresql+asyncpg://m:x@h/l")}, "LEDGER_ADMIN_DATABASE_URL"),
        ({}, "LEDGER_MIGRATOR_URL, LEDGER_ADMIN_DATABASE_URL"),
    ],
    ids=["no-migrator-url", "no-admin-url", "neither"],
)
def test_migrate_names_the_missing_settings(
    present: dict[str, SecretStr], missing_env: str
) -> None:
    with pytest.raises(MigrationSettingsError, match=f"^{missing_env} must be set"):
        migrate(APP_ONLY.model_copy(update=present))
