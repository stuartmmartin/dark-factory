"""The compose file's security posture: published ports stay on the loopback interface."""

import re
from pathlib import Path
from typing import Any, cast

import yaml

REPO = Path(__file__).resolve().parents[3]


def _published_ports() -> dict[str, list[str]]:
    compose = cast(
        dict[str, Any], yaml.safe_load((REPO / "compose/docker-compose.yml").read_text())
    )
    services = cast(dict[str, dict[str, Any]], compose["services"])
    return {name: [str(p) for p in svc.get("ports", [])] for name, svc in services.items()}


def test_every_published_port_binds_to_loopback_only() -> None:
    ports = _published_ports()
    assert {"postgres", "kafka", "temporal", "kafka-ui"} <= {n for n, p in ports.items() if p}
    exposed = {
        name: port
        for name, published in ports.items()
        for port in published
        if not port.startswith("127.0.0.1:")
    }
    assert exposed == {}


def test_every_password_variable_is_required() -> None:
    """`${SB_*_PASSWORD}` with no guard interpolates to an empty password when the env file
    lacks it; `${VAR:?message}` makes compose refuse instead."""
    unguarded = [
        f"{name}: {match.group(0)}"
        for name in ("compose/docker-compose.yml", "compose/services.yml")
        for match in re.finditer(r"\$\{(SB_\w*PASSWORD)(?!:\?)[^}]*\}", (REPO / name).read_text())
    ]
    assert unguarded == []


def test_dockerignore_keeps_every_env_file_out_of_the_build_context() -> None:
    lines = (REPO / ".dockerignore").read_text().splitlines()
    for pattern in (".env", ".env.*", "**/.env", "**/.env.*", "!**/.env.example"):
        assert pattern in lines


def _service_environments() -> dict[str, dict[str, str]]:
    compose = cast(dict[str, Any], yaml.safe_load((REPO / "compose/services.yml").read_text()))
    services = cast(dict[str, dict[str, Any]], compose["services"])
    return {name: dict(svc.get("environment") or {}) for name, svc in services.items()}


def test_only_the_api_gets_the_admin_credentials() -> None:
    """Least privilege: the worker, consumer and migrate job never mount the admin."""
    holders = {
        name
        for name, env in _service_environments().items()
        if any(
            key.endswith(("_ADMIN_USERNAME", "_ADMIN_PASSWORD", "_ADMIN_SECRET_KEY")) for key in env
        )
    }
    assert holders == {"ledger-api"}
