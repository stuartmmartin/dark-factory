import pytest
from pydantic import ValidationError

from ledger.infrastructure.settings import load_settings

BASE = {
    "LEDGER_ENVIRONMENT": "test",
    "LEDGER_AUTH_MODE": "dev",
    "LEDGER_DATABASE_URL": "postgresql+asyncpg://sb_app:x@h/ledger",
    "LEDGER_MIGRATOR_URL": "postgresql+asyncpg://sb_migrator:x@h/ledger",
    "LEDGER_ADMIN_DATABASE_URL": "postgresql+asyncpg://sb_admin:x@h/postgres",
    "LEDGER_ADMIN_USERNAME": "admin",
    "LEDGER_ADMIN_PASSWORD": "pw",
    "LEDGER_ADMIN_SECRET_KEY": "k" * 32,
}


def _env(monkeypatch: pytest.MonkeyPatch, values: dict[str, str]) -> None:
    for k, v in values.items():
        monkeypatch.setenv(k, v)


def test_reads_prefixed_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, BASE)
    settings = load_settings()
    assert settings.environment == "test"
    assert settings.database_name == "ledger"
    assert settings.database_url.get_secret_value().startswith("postgresql+asyncpg://sb_app")


@pytest.mark.parametrize("missing", ["LEDGER_ENVIRONMENT", "LEDGER_AUTH_MODE"])
def test_environment_and_auth_mode_are_required(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    _env(monkeypatch, {k: v for k, v in BASE.items() if k != missing})
    monkeypatch.delenv(missing, raising=False)
    with pytest.raises(ValidationError, match=missing.removeprefix("LEDGER_").lower()):
        load_settings()


def test_dev_auth_in_prod_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, {**BASE, "LEDGER_ENVIRONMENT": "prod", "LEDGER_AUTH_MODE": "dev"})
    with pytest.raises(ValidationError, match="dev auth"):
        load_settings()


ADMIN = ("LEDGER_ADMIN_USERNAME", "LEDGER_ADMIN_PASSWORD", "LEDGER_ADMIN_SECRET_KEY")


def test_non_api_processes_load_without_admin_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """The worker, consumer, migrate and seed never mount the admin, so they never get its
    credentials (least privilege); only the API requires them, in `admin_credentials()`."""
    for name in ADMIN:
        monkeypatch.delenv(name, raising=False)
    _env(monkeypatch, {k: v for k, v in BASE.items() if k not in ADMIN})
    settings = load_settings()
    assert settings.admin_username is None
    assert settings.admin_secret_key is None


def test_admin_credentials_are_returned_when_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, BASE)
    credentials = load_settings().admin_credentials()
    assert (credentials.username, credentials.password) == ("admin", "pw")
    assert credentials.secret_key == "k" * 32


@pytest.mark.parametrize("secret", ["short", "k" * 31])
def test_short_admin_secret_is_refused(monkeypatch: pytest.MonkeyPatch, secret: str) -> None:
    _env(monkeypatch, {**BASE, "LEDGER_ADMIN_SECRET_KEY": secret})
    settings = load_settings()
    with pytest.raises(ValueError, match="at least 32"):
        settings.admin_credentials()


def test_prod_with_oidc_needs_no_admin_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    prod = {k: v for k, v in BASE.items() if k not in ADMIN}
    _env(monkeypatch, {**prod, "LEDGER_ENVIRONMENT": "prod", "LEDGER_AUTH_MODE": "oidc"})
    assert load_settings().admin_secret_key is None


@pytest.mark.parametrize("missing", ADMIN)
def test_each_missing_admin_field_is_refused(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    _env(monkeypatch, {k: v for k, v in BASE.items() if k != missing})
    monkeypatch.delenv(missing, raising=False)
    settings = load_settings()
    with pytest.raises(ValueError, match="required to mount the admin"):
        settings.admin_credentials()


@pytest.mark.parametrize("empty", ADMIN)
def test_empty_admin_credentials_are_refused(monkeypatch: pytest.MonkeyPatch, empty: str) -> None:
    _env(monkeypatch, {**BASE, empty: ""})
    settings = load_settings()
    with pytest.raises(ValueError, match="required to mount the admin"):
        settings.admin_credentials()


def test_the_app_processes_need_no_privileged_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only `ledger.migrate` uses the migrator and admin URLs; the API, worker, consumer and seed
    run without them (M4)."""
    for name in ("LEDGER_MIGRATOR_URL", "LEDGER_ADMIN_DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    _env(
        monkeypatch,
        {
            k: v
            for k, v in BASE.items()
            if k not in {"LEDGER_MIGRATOR_URL", "LEDGER_ADMIN_DATABASE_URL"}
        },
    )
    settings = load_settings()
    assert settings.migrator_url is None
    assert settings.admin_database_url is None
