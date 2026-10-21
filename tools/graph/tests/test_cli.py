import json
from pathlib import Path

import pytest

from sb_graph.cli import main


@pytest.fixture
def repo(workspace: Path, add_member) -> Path:
    add_member("libs/py/sb_kernel", "sb-kernel", files={"src/sb_kernel/__init__.py": ""})
    add_member(
        "services/ledger",
        "ledger",
        deps=["sb-kernel"],
        files={"src/ledger/__init__.py": "import sb_kernel\n"},
    )
    (workspace / "tach.toml").write_text(
        'source_roots = ["libs/py/sb_kernel/src", "services/ledger/src"]\n'
    )
    (workspace / ".importlinter").write_text("""
[importlinter]
include_external_packages = True
root_packages = sb_kernel
 ledger
[importlinter:contract:ledger-layers]
type = layers
containers = ledger
layers = main | (worker) | (consumer) | (seed)
 bootstrap | migrate
 interface
 infrastructure
 application
 domain
[importlinter:contract:ledger-pure-core]
type = forbidden
source_modules = ledger.domain
 ledger.application
forbidden_modules = sqlalchemy
 fastapi
 starlette
 sqladmin
 temporalio
 confluent_kafka
 httpx
 pydantic_settings
 structlog
[importlinter:contract:libs-never-import-services]
type = forbidden
source_modules = sb_kernel
forbidden_modules = ledger
""")
    return workspace


def test_generate_then_check_passes(repo: Path) -> None:
    assert main(["--root", str(repo), "generate"]) == 0
    assert (repo / "docs/generated/build-graph.json").is_file()
    assert main(["--root", str(repo), "check"]) == 0


def test_check_rejects_partial_service_registration(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--root", str(repo), "generate"]) == 0
    (repo / ".importlinter").write_text("[importlinter]\nroot_packages = sb_kernel\n ledger\n")
    assert main(["--root", str(repo), "check"]) == 1
    assert "ledger-layers" in capsys.readouterr().err


def test_check_fails_when_generated_files_are_stale(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["--root", str(repo), "generate"])
    (repo / "docs/generated/module-index.md").write_text("edited by hand\n")
    assert main(["--root", str(repo), "check"]) == 1
    assert "module-index.md is stale; run `make graph`" in capsys.readouterr().err


def test_check_fails_on_undeclared_dependency(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / "libs/py/sb_kernel/src/sb_kernel/__init__.py").write_text("import ledger\n")
    main(["--root", str(repo), "generate"])
    assert main(["--root", str(repo), "check"]) == 1
    assert "imports ledger but does not declare it" in capsys.readouterr().err


def test_members_json_is_a_github_matrix(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--root", str(repo), "members", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "include": [
            {"name": "ledger", "path": "services/ledger", "import_name": "ledger"},
            {"name": "sb-kernel", "path": "libs/py/sb_kernel", "import_name": "sb_kernel"},
        ]
    }


def test_members_can_discover_only_service_import_names(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = repo / "services/ledger/pyproject.toml"
    config.write_text(config.read_text() + '\n[tool.sb]\nimport-name = "ledger_api"\n')
    assert main(["--root", str(repo), "members", "--kind", "service", "--format", "imports"]) == 0
    assert capsys.readouterr().out.split() == ["ledger_api"]


def test_members_json_resolves_an_underscored_service(
    workspace: Path, add_member, capsys: pytest.CaptureFixture[str]
) -> None:
    """images.yml builds `<path>/Dockerfile` with SERVICE=<import_name>, and names the image and
    the k8s directory (`deploy/k8s/<name>/`) by the normalized, hyphenated `name`."""
    add_member("services/demo_svc", "demo_svc", files={"src/demo_svc/__init__.py": ""})
    assert main(["--root", str(workspace), "members", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "include": [{"name": "demo-svc", "path": "services/demo_svc", "import_name": "demo_svc"}]
    }


def test_broken_member_config_exits_two_with_message(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / "services/ledger/pyproject.toml").write_text("[project\n")
    assert main(["--root", str(repo), "members"]) == 2
    assert "services/ledger/pyproject.toml" in capsys.readouterr().err


def test_blast_radius_and_deps(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--root", str(repo), "blast-radius", "sb-kernel"]) == 0
    assert capsys.readouterr().out.split() == ["ledger"]
    assert main(["--root", str(repo), "deps", "ledger"]) == 0
    assert capsys.readouterr().out.split() == ["sb-kernel"]


def test_blast_radius_of_unknown_member_exits_two(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--root", str(repo), "blast-radius", "nope"]) == 2
    assert "unknown member" in capsys.readouterr().err


def test_affected_with_missing_base_exits_two_with_hint(
    repo: Path, git, capsys: pytest.CaptureFixture[str]
) -> None:
    git(repo, "init", "-q", "-b", "main")
    assert main(["--root", str(repo), "affected", "--base", "origin/main"]) == 2
    assert "git fetch" in capsys.readouterr().err


def test_check_reports_uncovered_member(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["--root", str(repo), "generate"])
    (repo / "tach.toml").write_text('source_roots = ["libs/py/sb_kernel/src"]\n')
    assert main(["--root", str(repo), "check"]) == 1
    assert "services/ledger/src is not in tach source_roots" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["check", "generate"])
def test_syntax_error_in_member_src_exits_two_naming_file_and_line(
    repo: Path, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    (repo / "services/ledger/src/ledger/api.py").write_text("x = 1\ndef broken(:\n")
    assert main(["--root", str(repo), command]) == 2
    assert "services/ledger/src/ledger/api.py:2: syntax error" in capsys.readouterr().err
