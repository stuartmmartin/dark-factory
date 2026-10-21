"""The client's configuration (C5): flags override these, which come from LEDGER_CLI_* variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

DEMO_TENANT = "00000000-0000-0000-0000-0000000000d3"  # the tenant `make seed SVC=ledger` uses


class ClientSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LEDGER_CLI_", extra="ignore")

    url: str = "http://localhost:8001"
    tenant: str = DEMO_TENANT
    timeout_seconds: float = 10.0
