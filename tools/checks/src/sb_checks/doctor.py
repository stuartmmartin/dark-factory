"""Environment diagnostics for `make doctor`: tools, Docker, ports, dev secrets.

Reads the process environment only. It never opens or parses `.env` (C14).
"""

from __future__ import annotations

import shlex
import shutil
import socket
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

__all__ = ["DEFAULT_COMPOSE", "PS_ARGS", "Finding", "Probe", "Status", "SystemProbe", "diagnose"]

Status = Literal["ok", "warn", "fail"]
DEFAULT_COMPOSE = "docker compose -f compose/docker-compose.yml"
PS_ARGS = ["--profile", "*", "ps", "--services", "--status", "running"]
PORTS = (
    ("SB_PG_PORT", 5432, "postgres"),
    ("SB_KAFKA_PORT", 9092, "kafka"),
    ("SB_TEMPORAL_PORT", 7233, "temporal"),
    ("SB_TEMPORAL_UI_PORT", 8233, "temporal"),
)
REQUIRED = {
    "uv": "install uv: https://docs.astral.sh/uv/ (or `brew install uv`)",
    "docker": "install Docker Desktop, OrbStack or colima",
}
OPTIONAL = {
    "mise": "install mise (`brew install mise`) to get pinned tool versions",
    "gitleaks": "install gitleaks (`mise install` or `brew install gitleaks`) for pre-commit",
    "pyright-langserver": "run `make bootstrap` (installs pyright for the Claude LSP plugin)",
}
PROBE_TIMEOUT = 20
ADMIN_SECRET_VARIABLE = "SB_ADMIN_SECRET_KEY"  # noqa: S105 - a variable name, not a secret
MIN_ADMIN_SECRET_LENGTH = 32


@dataclass(frozen=True)
class Finding:
    name: str
    status: Status
    detail: str


class Probe(Protocol):
    def which(self, tool: str) -> str | None: ...
    def run(self, argv: Sequence[str]) -> tuple[int, str]: ...
    def port_free(self, port: int) -> bool: ...
    def exists(self, path: str) -> bool: ...


class SystemProbe:
    def __init__(self, root: Path) -> None:
        self.root = root

    def which(self, tool: str) -> str | None:
        return shutil.which(tool)

    def run(self, argv: Sequence[str]) -> tuple[int, str]:
        try:
            done = subprocess.run(  # noqa: S603 - fixed argv lists defined in this module
                list(argv),
                cwd=self.root,
                capture_output=True,
                text=True,
                check=False,
                timeout=PROBE_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 1, str(exc)
        return done.returncode, done.stdout + done.stderr

    def port_free(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(2)
            return sock.connect_ex(("127.0.0.1", port)) != 0

    def exists(self, path: str) -> bool:
        return (self.root / path).exists()


def _tools(probe: Probe) -> list[Finding]:
    findings = [
        Finding(tool, "ok", path) if (path := probe.which(tool)) else Finding(tool, "fail", hint)
        for tool, hint in REQUIRED.items()
    ]
    findings += [
        Finding(tool, "ok", path) if (path := probe.which(tool)) else Finding(tool, "warn", hint)
        for tool, hint in OPTIONAL.items()
    ]
    return findings


def _docker(probe: Probe) -> list[Finding]:
    if probe.which("docker") is None:
        return []
    daemon, _ = probe.run(["docker", "info"])
    compose, _ = probe.run(["docker", "compose", "version"])
    return [
        Finding(
            "docker daemon",
            "ok" if daemon == 0 else "fail",
            "running" if daemon == 0 else "start Docker Desktop / OrbStack / colima",
        ),
        Finding(
            "docker compose v2",
            "ok" if compose == 0 else "fail",
            "available" if compose == 0 else "install the Docker Compose v2 plugin",
        ),
    ]


def _ports(probe: Probe, env: Mapping[str, str], compose: str) -> list[Finding]:
    code, running = probe.run([*shlex.split(compose), *PS_ARGS])
    ours: set[str] = set(running.split()) if code == 0 else set()
    findings: list[Finding] = []
    for variable, default, service in PORTS:
        raw = env.get(variable, str(default))
        try:
            port = int(raw)
        except ValueError:
            findings.append(Finding(variable, "warn", f"{variable}={raw!r} is not a port number"))
            continue
        if probe.port_free(port) or service in ours:
            findings.append(Finding(f"port {port}", "ok", f"{variable} free or used by our stack"))
        elif code != 0:
            findings.append(
                Finding(
                    f"port {port}",
                    "warn",
                    f"port {port} is busy and could not query the compose stack "
                    f"({running.strip()[:80]}); change {variable} if it is not ours",
                )
            )
        else:
            findings.append(
                Finding(
                    f"port {port}",
                    "warn",
                    f"port {port} is used by another process; set {variable} in .env to a free one",
                )
            )
    return findings


def _admin_secret(env: Mapping[str, str]) -> list[Finding]:
    """Warn on a short admin session secret in the process env; never echo its value."""
    secret = env.get(ADMIN_SECRET_VARIABLE)
    if secret is None:
        return []
    if len(secret) < MIN_ADMIN_SECRET_LENGTH:
        return [
            Finding(
                "admin secret",
                "warn",
                f"{ADMIN_SECRET_VARIABLE} is shorter than {MIN_ADMIN_SECRET_LENGTH} characters; "
                "sb_admin refuses it. Use a long random value",
            )
        ]
    return [Finding("admin secret", "ok", f"{ADMIN_SECRET_VARIABLE} is long enough")]


def diagnose(probe: Probe, env: Mapping[str, str], compose: str = DEFAULT_COMPOSE) -> list[Finding]:
    hooks = probe.exists(".venv/bin/sb-agentkit")
    return [
        *_tools(probe),
        *_docker(probe),
        Finding(
            "agent hooks",
            "ok" if hooks else "warn",
            "sb-agentkit installed" if hooks else "run `make bootstrap` so Claude hooks work",
        ),
        *_ports(probe, env, compose),
        *_admin_secret(env),
    ]
