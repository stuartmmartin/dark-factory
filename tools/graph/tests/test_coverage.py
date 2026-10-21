from pathlib import Path

import pytest

from sb_graph.coverage import coverage_errors
from sb_graph.graph import load_graph

ROOT_TOML = """\
[tool.uv.workspace]
members = ["libs/py/*", "services/*"]

[tool.pytest.ini_options]
testpaths = {testpaths}

[tool.pyright]
include = {include}

[tool.importlinter]
root_packages = {root_packages}
"""


@pytest.fixture
def repo(workspace: Path, add_member) -> Path:
    add_member("libs/py/sb_kernel", "sb-kernel", files={"src/sb_kernel/__init__.py": ""})
    add_member("services/ledger", "ledger", files={"src/ledger/__init__.py": ""})
    add_member("services/no_src", "no-src")
    return workspace


def _configure(
    root: Path,
    *,
    testpaths: str = '["libs", "services"]',
    include: str = '["libs", "services/*/src"]',
    root_packages: str = '["sb_kernel", "ledger"]',
    source_roots: str = '["libs/py/sb_kernel/src", "./services/ledger/src"]',
) -> None:
    (root / "pyproject.toml").write_text(
        ROOT_TOML.format(testpaths=testpaths, include=include, root_packages=root_packages)
    )
    (root / "tach.toml").write_text(f"source_roots = {source_roots}\n")


def test_fully_covered_workspace_has_no_errors(repo: Path) -> None:
    _configure(repo)
    assert coverage_errors(repo, load_graph(repo)) == []


def test_missing_pytest_testpath_names_pyproject(repo: Path) -> None:
    _configure(repo, testpaths='["libs"]')
    assert coverage_errors(repo, load_graph(repo)) == [
        "ledger: services/ledger is not under pytest testpaths; "
        "add it to pyproject.toml [tool.pytest.ini_options].testpaths"
    ]


def test_missing_pyright_include_names_pyproject(repo: Path) -> None:
    _configure(repo, include='["services/*/src"]')
    assert coverage_errors(repo, load_graph(repo)) == [
        "sb-kernel: libs/py/sb_kernel/src is not in pyright include; "
        "add it to pyproject.toml [tool.pyright].include"
    ]


def test_missing_tach_source_root_names_tach_toml(repo: Path) -> None:
    _configure(repo, source_roots='["libs/py/sb_kernel/src"]')
    assert coverage_errors(repo, load_graph(repo)) == [
        "ledger: services/ledger/src is not in tach source_roots; add it to tach.toml source_roots"
    ]


def test_missing_import_linter_root_package_names_pyproject(repo: Path) -> None:
    _configure(repo, root_packages='["ledger"]')
    assert coverage_errors(repo, load_graph(repo)) == [
        "sb-kernel: sb_kernel is not in import-linter root_packages; "
        "add it to pyproject.toml [tool.importlinter].root_packages"
    ]


def test_importlinter_ini_takes_precedence_over_pyproject(repo: Path) -> None:
    _configure(repo, root_packages="[]")
    (repo / ".importlinter").write_text("[importlinter]\nroot_packages =\n    sb_kernel\n")
    assert coverage_errors(repo, load_graph(repo)) == [
        "ledger: ledger is not in import-linter root_packages; "
        "add it to .importlinter [importlinter] root_packages"
    ]


def test_missing_tach_toml_and_import_linter_config_are_errors(repo: Path) -> None:
    errors = coverage_errors(repo, load_graph(repo))
    assert "ledger: services/ledger/src is not in tach source_roots; " in errors[0]
    assert sum("tach.toml" in e for e in errors) == 2
    assert sum("import-linter" in e for e in errors) == 2


def test_absent_pytest_and_pyright_settings_cover_the_whole_repo(repo: Path) -> None:
    (repo / "tach.toml").write_text(
        'source_roots = ["libs/py/sb_kernel/src", "services/ledger/src"]\n'
    )
    (repo / ".importlinter").write_text("[importlinter]\nroot_packages = sb_kernel\n  ledger\n")
    assert coverage_errors(repo, load_graph(repo)) == []


def test_pyrightconfig_json_takes_precedence_over_pyproject(repo: Path) -> None:
    """pyright ignores [tool.pyright] when pyrightconfig.json exists, so coverage must too."""
    _configure(repo, include="[]")
    (repo / "pyrightconfig.json").write_text('{"include": ["libs", "services/*/src"]}\n')
    assert coverage_errors(repo, load_graph(repo)) == []


def test_missing_pyrightconfig_json_include_names_pyrightconfig(repo: Path) -> None:
    _configure(repo)
    (repo / "pyrightconfig.json").write_text('{"include": ["services/*/src"]}\n')
    assert coverage_errors(repo, load_graph(repo)) == [
        "sb-kernel: libs/py/sb_kernel/src is not in pyright include; "
        "add it to pyrightconfig.json include"
    ]
