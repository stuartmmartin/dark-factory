"""Ledger settings: the only place environment variables are read (C5)."""

from dataclasses import dataclass, field
from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Same allowlist as sb_http.auth and sb_admin.auth: dev auth is refused anywhere else.
DEV_ENVIRONMENTS = frozenset({"local", "dev", "test", "ci"})
MIN_ADMIN_SECRET_LENGTH = 32


@dataclass(frozen=True)
class AdminCredentials:
    """The SQLAdmin login and session secret, validated (see `Settings.admin_credentials`)."""

    username: str
    password: str = field(repr=False)  # never printed
    secret_key: str = field(repr=False)


class Settings(BaseSettings):
    """Service configuration, read from `LEDGER_*` environment variables."""

    model_config = SettingsConfigDict(env_prefix="LEDGER_", extra="ignore")

    environment: Literal["local", "dev", "test", "ci", "prod"]
    auth_mode: Literal["dev", "oidc"]
    database_url: SecretStr
    # Only `ledger.migrate` needs these privileged URLs (it refuses to run without them); the
    # API, worker, consumer and seed never receive them.
    migrator_url: SecretStr | None = None
    admin_database_url: SecretStr | None = None
    database_name: str = "ledger"
    kafka_bootstrap: str = "localhost:9092"
    temporal_target: str = "localhost:7233"
    temporal_namespace: str = "default"
    task_queue: str = "ledger"
    # Only the API mounts the admin (outside prod), so only the API process is given these;
    # `build_api` calls `admin_credentials()`, which fails fast when they are missing.
    admin_username: str | None = None
    admin_password: SecretStr | None = None
    admin_secret_key: SecretStr | None = None
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _check_environment_rules(self) -> Self:
        if self.auth_mode == "dev" and self.environment not in DEV_ENVIRONMENTS:
            raise ValueError(
                f"dev auth is not allowed in environment {self.environment!r}; "
                f"allowed: {sorted(DEV_ENVIRONMENTS)}"
            )
        return self

    def admin_credentials(self) -> AdminCredentials:
        """The admin's credentials; raises `ValueError` if any is missing or empty, or the secret
        key is shorter than 32 characters. Called by the API before it mounts the admin."""
        password = self.admin_password.get_secret_value() if self.admin_password else ""
        secret = self.admin_secret_key.get_secret_value() if self.admin_secret_key else ""
        if not self.admin_username or not password or not secret:
            raise ValueError(
                "LEDGER_ADMIN_USERNAME, LEDGER_ADMIN_PASSWORD and LEDGER_ADMIN_SECRET_KEY are "
                "required to mount the admin (the API outside prod)"
            )
        if len(secret) < MIN_ADMIN_SECRET_LENGTH:
            raise ValueError(
                f"admin secret key must be at least {MIN_ADMIN_SECRET_LENGTH} characters"
            )
        return AdminCredentials(self.admin_username, password, secret)


def load_settings() -> Settings:
    """Build Settings from the environment; the only call site of `Settings()`."""
    # pydantic-settings fills the required fields from env vars, which pyright cannot see.
    return Settings()  # pyright: ignore[reportCallIssue]
