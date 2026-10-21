"""`sb-checks openapi`: render a service's OpenAPI document and write or drift-check it.

The service is imported by name at run time (`<service>.bootstrap.build_api` and
`<service>.infrastructure.settings.Settings`), so sb_checks has no static dependency on any
service. The app is built with explicit test settings: `environment` has no default (D1).
Building it creates an engine but never connects.
"""

from __future__ import annotations

import importlib
import json
import re
from pathlib import Path
from typing import Any

__all__ = [
    "CONTRACTS_DIR",
    "TEST_SETTINGS",
    "ServiceNameError",
    "check",
    "contract_path",
    "render",
    "write",
]

CONTRACTS_DIR = Path("contracts") / "openapi"
_SERVICE_RE = re.compile(r"[a-z][a-z0-9_]*")
_PLACEHOLDER_DB = "postgresql+asyncpg://openapi:openapi@localhost:5432/openapi"

TEST_SETTINGS: dict[str, str] = {
    "environment": "test",
    "auth_mode": "dev",
    "database_url": _PLACEHOLDER_DB,
    "migrator_url": _PLACEHOLDER_DB,
    "admin_database_url": _PLACEHOLDER_DB,
    "admin_username": "openapi",
    "admin_password": "openapi",
    "admin_secret_key": "openapi-placeholder-secret-key-000",
}


class ServiceNameError(ValueError):
    """The service name is not a plain lowercase package name."""


def _checked(service: str) -> str:
    if not _SERVICE_RE.fullmatch(service):
        raise ServiceNameError(f"service must match {_SERVICE_RE.pattern}, got {service!r}")
    return service


def contract_path(root: Path, service: str) -> Path:
    return root / CONTRACTS_DIR / f"{_checked(service)}.json"


def render(service: str) -> str:
    """The service's OpenAPI document as stable JSON (sorted keys, trailing newline)."""
    name = _checked(service)
    settings_cls: Any = importlib.import_module(f"{name}.infrastructure.settings").Settings
    build_api: Any = importlib.import_module(f"{name}.bootstrap").build_api
    # Not disposing the app's engine is safe: `openapi()` never touches the database, so the
    # pool never opens a connection (nothing to close), and this is a one-shot CLI process.
    # Disposing would also need service-specific knowledge of where the engine lives.
    document: Any = build_api(settings_cls(**TEST_SETTINGS)).openapi()
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write(root: Path, service: str) -> Path:
    path = contract_path(root, service)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(service))
    return path


def check(root: Path, service: str) -> str | None:
    """None when the committed contract matches the app; otherwise why it does not."""
    path = contract_path(root, service)
    if not path.is_file():
        return f"{path.relative_to(root)} is missing; run `make openapi`"
    if path.read_text() != render(service):
        return f"{path.relative_to(root)} is out of date with the app; run `make openapi`"
    return None
