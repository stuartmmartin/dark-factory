from pathlib import Path, PurePosixPath

import pytest

from sb_graph.graph import GraphError, load_graph, validate


@pytest.fixture
def three_layer(workspace: Path, add_member) -> Path:
    add_member("libs/py/sb_kernel", "sb-kernel", files={"src/sb_kernel/__init__.py": ""})
    add_member(
        "libs/py/sb_db",
        "sb-db",
        deps=["sb-kernel"],
        files={"src/sb_db/__init__.py": "import sb_kernel\n"},
    )
    add_member(
        "services/ledger",
        "ledger",
        deps=["sb-db"],
        files={"src/ledger/__init__.py": "import sb_db\n"},
    )
    return workspace


def test_edges_and_closures(three_layer: Path) -> None:
    graph = load_graph(three_layer)
    assert graph.edges == (("ledger", "sb-db"), ("sb-db", "sb-kernel"))
    assert graph.deps_closure("ledger") == ("sb-db", "sb-kernel")
    assert graph.dependents_closure("sb-kernel") == ("ledger", "sb-db")
    assert graph.dependents("sb-kernel") == ("sb-db",)


def test_owner_of_uses_member_directory(three_layer: Path) -> None:
    graph = load_graph(three_layer)
    owner = graph.owner_of(PurePosixPath("libs/py/sb_db/src/sb_db/uow.py"))
    assert owner is not None
    assert owner.name == "sb-db"
    assert graph.owner_of(PurePosixPath("docs/README.md")) is None


def test_unknown_member_raises_graph_error_listing_known(three_layer: Path) -> None:
    with pytest.raises(GraphError, match="sb-kernel"):
        load_graph(three_layer).member("nope")


def test_validate_passes_when_declared_matches_imports(three_layer: Path) -> None:
    assert validate(three_layer, load_graph(three_layer)) == []


def test_validate_reports_undeclared_and_unused(workspace: Path, add_member) -> None:
    add_member("libs/py/sb_kernel", "sb-kernel", files={"src/sb_kernel/__init__.py": ""})
    add_member("libs/py/sb_obs", "sb-obs", files={"src/sb_obs/__init__.py": ""})
    add_member(
        "services/ledger",
        "ledger",
        deps=["sb-obs"],
        files={"src/ledger/__init__.py": "import sb_kernel\n"},
    )
    errors = validate(workspace, load_graph(workspace))
    assert any("imports sb-kernel but does not declare it" in e for e in errors)
    assert any("declares sb-obs but never imports it" in e for e in errors)


def test_validate_reports_cycles(workspace: Path, add_member) -> None:
    add_member(
        "libs/py/sb_a", "sb-a", deps=["sb-b"], files={"src/sb_a/__init__.py": "import sb_b\n"}
    )
    add_member(
        "libs/py/sb_b", "sb-b", deps=["sb-a"], files={"src/sb_b/__init__.py": "import sb_a\n"}
    )
    errors = validate(workspace, load_graph(workspace))
    assert any("cycle" in e for e in errors)


@pytest.fixture
def with_testkit(workspace: Path, add_member) -> Path:
    add_member("libs/py/sb_kernel", "sb-kernel", files={"src/sb_kernel/__init__.py": ""})
    add_member(
        "libs/py/sb_testkit",
        "sb-testkit",
        deps=["sb-kernel"],
        files={"src/sb_testkit/__init__.py": "import sb_kernel\n"},
    )
    add_member(
        "services/ledger",
        "ledger",
        files={"src/ledger/__init__.py": ""},
        extra_toml='[dependency-groups]\ntest = ["sb-testkit"]\n',
    )
    return workspace


def test_test_edges_are_separate_from_runtime_edges(with_testkit: Path) -> None:
    graph = load_graph(with_testkit)
    assert graph.edges == (("sb-testkit", "sb-kernel"),)
    assert graph.test_edges == (("ledger", "sb-testkit"),)


def test_blast_radius_follows_test_edges(with_testkit: Path) -> None:
    graph = load_graph(with_testkit)
    assert graph.dependents_closure("sb-kernel") == ("ledger", "sb-testkit")
    assert graph.deps_closure("ledger") == ()


def test_validate_ignores_test_only_dependencies(with_testkit: Path) -> None:
    assert validate(with_testkit, load_graph(with_testkit)) == []
