"""Registering a package alone must never count as registering its architecture policy."""

from pathlib import Path

import pytest

from sb_graph.graph import load_graph
from sb_graph.service_contracts import service_contract_errors

FRAMEWORKS = (
    "sqlalchemy fastapi starlette sqladmin temporalio confluent_kafka "
    "httpx pydantic_settings structlog"
)


def contracts(services: tuple[str, ...] = ("ledger",)) -> str:
    text = (
        "[importlinter]\ninclude_external_packages = True\nroot_packages = sb_kernel\n sb_testing\n"
    )
    text += "".join(f" {s}\n" for s in services)
    text += """
[importlinter:contract:libs-never-import-services]
type = forbidden
source_modules = sb_kernel
 sb_testing
forbidden_modules =
""" + "".join(f" {s}\n" for s in services)
    text += (
        """
[importlinter:contract:testing-only-in-tests]
type = forbidden
source_modules = sb_kernel
"""
        + "".join(f" {s}\n" for s in services)
        + "forbidden_modules = sb_testing\n"
    )
    if len(services) > 1:
        text += "\n[importlinter:contract:services-independent]\ntype = independence\nmodules =\n"
        text += "".join(f" {s}\n" for s in services)
    for service in services:
        text += f"""
[importlinter:contract:{service}-layers]
type = layers
containers = {service}
layers =
 main | (worker) | (consumer) | (seed)
 bootstrap | migrate
 interface
 infrastructure
 application
 domain

[importlinter:contract:{service}-pure-core]
type = forbidden
source_modules = {service}.domain
 {service}.application
forbidden_modules =
""" + "".join(f" {f}\n" for f in (*FRAMEWORKS.split(), "sb_testing"))
    return text


@pytest.fixture
def repo(workspace: Path, add_member) -> Path:
    for path, name in [
        ("libs/py/sb_kernel", "sb_kernel"),
        ("libs/py/sb_testing", "sb_testing"),
        ("services/ledger", "ledger"),
        ("services/payments", "payments"),
    ]:
        add_member(path, name, files={f"src/{name}/__init__.py": ""})
    (workspace / ".importlinter").write_text(contracts(("ledger", "payments")))
    return workspace


def test_complete_registration_passes(repo: Path) -> None:
    assert service_contract_errors(repo, load_graph(repo)) == []


@pytest.mark.parametrize(
    "contract",
    [
        "ledger-layers",
        "ledger-pure-core",
        "services-independent",
        "libs-never-import-services",
        "testing-only-in-tests",
    ],
)
def test_missing_contract_fails(repo: Path, contract: str) -> None:
    path = repo / ".importlinter"
    # Renaming a section makes it unavailable under the generator's required contract name.
    path.write_text(
        path.read_text().replace(f"contract:{contract}]", f"contract:missing-{contract}]")
    )
    errors = service_contract_errors(repo, load_graph(repo))
    assert any(contract in error for error in errors), errors


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (" bootstrap | migrate", " bootstrap"),
        (" application\n domain", " domain\n application"),
        (" ledger.application", " ledger.domain"),
        (" httpx\n", ""),
        ("include_external_packages = True", "include_external_packages = False"),
        ("include_external_packages = True", "include_external_packages = maybe"),
        ("modules =\n ledger\n payments", "modules =\n ledger"),
    ],
)
def test_incomplete_or_weakened_registration_fails(repo: Path, before: str, after: str) -> None:
    path = repo / ".importlinter"
    assert before in path.read_text()
    path.write_text(path.read_text().replace(before, after))
    assert service_contract_errors(repo, load_graph(repo))


@pytest.mark.parametrize(
    "weakening",
    [
        "ignore_imports = ledger.domain -> httpx\n",
        "allow_indirect_imports = True\n",
        "as_packages = False\n",
        "allow_indirect_imports = maybe\n",
        "as_packages = maybe\n",
    ],
)
def test_contract_cannot_exempt_imports(repo: Path, weakening: str) -> None:
    path = repo / ".importlinter"
    path.write_text(
        path.read_text().replace(
            "[importlinter:contract:ledger-pure-core]\n",
            "[importlinter:contract:ledger-pure-core]\n" + weakening,
        )
    )
    assert service_contract_errors(repo, load_graph(repo))


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("ledger-layers", "layers"),
        ("ledger-pure-core", "forbidden"),
        ("services-independent", "independence"),
    ],
)
def test_wrong_contract_type_is_rejected(repo: Path, name: str, kind: str) -> None:
    path = repo / ".importlinter"
    original = f"[importlinter:contract:{name}]\ntype = {kind}"
    assert original in path.read_text()
    path.write_text(
        path.read_text().replace(original, original.replace(f"type = {kind}", "type = wrong"))
    )
    errors = service_contract_errors(repo, load_graph(repo))
    assert f".importlinter: {name} must have type {kind}" in errors


def test_malformed_or_missing_policy_fails_closed(repo: Path) -> None:
    path = repo / ".importlinter"
    for contents in ("", "[broken"):
        path.write_text(contents)
        assert service_contract_errors(repo, load_graph(repo))
    path.unlink()
    assert service_contract_errors(repo, load_graph(repo))


def test_workspace_without_services_needs_no_service_contracts(workspace: Path, add_member) -> None:
    add_member("libs/py/sb_kernel", "sb-kernel", files={"src/sb_kernel/__init__.py": ""})
    assert service_contract_errors(workspace, load_graph(workspace)) == []
