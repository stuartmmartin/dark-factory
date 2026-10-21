"""Require the complete canonical architecture policy for every discovered service.

Root package registration alone does not enforce CLEAN layers, pure cores or service islands.
This structural gate complements (never replaces) import-linter's actual dependency analysis.
Policy evolution is human-owned: update the checker and service template together.
"""

from __future__ import annotations

import configparser
from pathlib import Path

from sb_graph.graph import Graph

_FRAMEWORKS = {
    "sqlalchemy",
    "fastapi",
    "starlette",
    "sqladmin",
    "temporalio",
    "confluent_kafka",
    "httpx",
    "pydantic_settings",
    "structlog",
}
_LAYERS = [
    {"main", "(worker)", "(consumer)", "(seed)"},
    {"bootstrap", "migrate"},
    {"interface"},
    {"infrastructure"},
    {"application"},
    {"domain"},
]


def _names(section: configparser.SectionProxy, key: str) -> set[str]:
    return {name.strip() for name in section.get(key, "").splitlines() if name.strip()}


class _Policy:
    def __init__(self, config: configparser.ConfigParser) -> None:
        self.config = config
        self.errors: list[str] = []

    def contract(self, name: str, kind: str) -> configparser.SectionProxy | None:
        heading = f"importlinter:contract:{name}"
        if not self.config.has_section(heading):
            self.errors.append(f".importlinter: missing required contract {name}")
            return None
        section = self.config[heading]
        if section.get("type") != kind:
            self.errors.append(f".importlinter: {name} must have type {kind}")
        try:
            weakened = (
                bool(_names(section, "ignore_imports"))
                or section.getboolean("allow_indirect_imports", fallback=False)
                or not section.getboolean("as_packages", fallback=True)
            )
        except ValueError:
            weakened = True
        if weakened:
            self.errors.append(f".importlinter: {name} must not exempt imports or descendants")
        return section

    def require(self, section: configparser.SectionProxy, key: str, expected: set[str]) -> None:
        missing = expected - _names(section, key)
        if missing:
            self.errors.append(
                f".importlinter: {section.name} {key} missing {', '.join(sorted(missing))}"
            )

    def forbidden(self, name: str, sources: set[str], targets: set[str]) -> None:
        section = self.contract(name, "forbidden")
        if section is not None:
            self.require(section, "source_modules", sources)
            self.require(section, "forbidden_modules", targets)

    def layers(self, service: str) -> None:
        section = self.contract(f"{service}-layers", "layers")
        if section is None:
            return
        self.require(section, "containers", {service})
        actual = [
            {part.strip() for part in row.split("|")}
            for row in section.get("layers", "").splitlines()
            if row.strip()
        ]
        if actual != _LAYERS:
            self.errors.append(
                f".importlinter: {service}-layers must declare the complete CLEAN order"
            )


def service_contract_errors(root: Path, graph: Graph) -> list[str]:
    members = [m for m in graph.members if (root / m.path / "src").is_dir()]
    services = {m.import_name for m in members if m.kind == "service"}
    if not services:
        return []
    libraries = {m.import_name for m in members if m.kind == "lib"}
    config = configparser.ConfigParser(interpolation=None)
    policy = _Policy(config)
    try:
        config.read_string((root / ".importlinter").read_text(encoding="utf-8"))
        if not config.getboolean("importlinter", "include_external_packages", fallback=False):
            policy.errors.append(
                ".importlinter: include_external_packages must be True for pure cores"
            )
    except (OSError, UnicodeError, configparser.Error, ValueError) as exc:
        return [f".importlinter: cannot inspect service contracts: {exc}"]
    for service in sorted(services):
        policy.layers(service)
        policy.forbidden(
            f"{service}-pure-core",
            {f"{service}.domain", f"{service}.application"},
            _FRAMEWORKS | (libraries - {"sb_kernel"}),
        )
    if libraries:
        policy.forbidden("libs-never-import-services", libraries, services)
    if "sb_testing" in libraries:
        policy.forbidden(
            "testing-only-in-tests", (libraries - {"sb_testing"}) | services, {"sb_testing"}
        )
    if len(services) > 1:
        section = policy.contract("services-independent", "independence")
        if section is not None:
            policy.require(section, "modules", services)
    return sorted(policy.errors)
