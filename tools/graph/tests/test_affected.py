from pathlib import Path, PurePosixPath

import pytest

from sb_graph.affected import GitError, affected_members, changed_files
from sb_graph.graph import load_graph


@pytest.fixture
def repo(workspace: Path, add_member, git) -> Path:
    add_member("libs/py/sb_kernel", "sb-kernel", files={"src/sb_kernel/__init__.py": ""})
    add_member(
        "libs/py/sb_db",
        "sb-db",
        deps=["sb-kernel"],
        files={"src/sb_db/__init__.py": "import sb_kernel\n", "src/sb_db/uow.py": ""},
    )
    add_member(
        "services/ledger",
        "ledger",
        deps=["sb-db"],
        files={"src/ledger/__init__.py": "import sb_db\n"},
    )
    add_member("tools/graph", "sb-graph", files={"src/sb_graph/__init__.py": ""})
    git(workspace, "init", "-q", "-b", "main")
    git(workspace, "add", "-A")
    git(workspace, "commit", "-q", "-m", "init")
    git(workspace, "checkout", "-q", "-b", "feature")
    return workspace


def _paths(*names: str) -> tuple[PurePosixPath, ...]:
    return tuple(PurePosixPath(n) for n in names)


def test_lib_change_affects_itself_and_transitive_dependents(repo: Path) -> None:
    graph = load_graph(repo)
    changed = _paths("libs/py/sb_kernel/src/sb_kernel/__init__.py")
    assert affected_members(graph, changed) == ("ledger", "sb-db", "sb-kernel")


def test_root_config_change_affects_everything(repo: Path) -> None:
    graph = load_graph(repo)
    assert affected_members(graph, _paths("uv.lock")) == (
        "ledger",
        "sb-db",
        "sb-graph",
        "sb-kernel",
    )
    assert len(affected_members(graph, _paths(".github/workflows/ci.yml"))) == 4


def test_docs_only_change_affects_nothing(repo: Path) -> None:
    assert affected_members(load_graph(repo), _paths("docs/README.md")) == ()


def test_committed_changes_since_base(repo: Path, git) -> None:
    (repo / "services/ledger/src/ledger/api.py").write_text("")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "change")
    assert changed_files(repo, "main", include_worktree=False) == _paths(
        "services/ledger/src/ledger/api.py"
    )


def test_deleted_file_still_maps_to_its_member(repo: Path, git) -> None:
    git(repo, "rm", "-q", "libs/py/sb_db/src/sb_db/uow.py")
    git(repo, "commit", "-q", "-m", "delete")
    changed = changed_files(repo, "main", include_worktree=False)
    assert affected_members(load_graph(repo), changed) == ("ledger", "sb-db")


def test_worktree_changes_include_modified_and_untracked(repo: Path) -> None:
    (repo / "libs/py/sb_db/src/sb_db/uow.py").write_text("x = 1\n")
    (repo / "tools/graph/src/sb_graph/new.py").write_text("")
    assert changed_files(repo, "main") == _paths(
        "libs/py/sb_db/src/sb_db/uow.py", "tools/graph/src/sb_graph/new.py"
    )


def test_missing_base_ref_raises_git_error_with_hint(repo: Path) -> None:
    with pytest.raises(GitError, match="git fetch"):
        changed_files(repo, "origin/does-not-exist")


def test_contracts_change_affects_everything(repo: Path) -> None:
    changed = _paths("contracts/events/ledger.v1.json")
    assert len(affected_members(load_graph(repo), changed)) == 4


def test_file_moved_between_members_marks_both(repo: Path, git) -> None:
    source = "tools/graph/src/sb_graph/walk.py"
    (repo / source).write_text("def walk():\n    return [1, 2, 3]\n" * 5)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "add walk")
    git(repo, "checkout", "-q", "-b", "move")
    git(repo, "mv", source, "services/ledger/src/ledger/walk.py")
    git(repo, "commit", "-q", "-m", "move walk")
    changed = changed_files(repo, "feature", include_worktree=False)
    assert changed == _paths("services/ledger/src/ledger/walk.py", source)
    assert affected_members(load_graph(repo), changed) == ("ledger", "sb-graph")


def test_uncommitted_move_marks_both(repo: Path, git) -> None:
    git(repo, "mv", "libs/py/sb_db/src/sb_db/uow.py", "tools/graph/src/sb_graph/uow.py")
    changed = changed_files(repo, "main")
    assert PurePosixPath("libs/py/sb_db/src/sb_db/uow.py") in changed
    assert PurePosixPath("tools/graph/src/sb_graph/uow.py") in changed


def test_non_ascii_paths_map_to_their_member(repo: Path, git) -> None:
    (repo / "services/ledger/src/ledger/café.py").write_text("x = 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "accent")
    (repo / "tools/graph/src/sb_graph/naïve.py").write_text("")
    changed = changed_files(repo, "main")
    assert changed == _paths(
        "services/ledger/src/ledger/café.py", "tools/graph/src/sb_graph/naïve.py"
    )
    assert affected_members(load_graph(repo), changed) == ("ledger", "sb-graph")


def test_test_only_dependency_marks_the_dependent(workspace: Path, add_member) -> None:
    add_member("libs/py/sb_testkit", "sb-testkit", files={"src/sb_testkit/__init__.py": ""})
    add_member(
        "services/ledger",
        "ledger",
        files={"src/ledger/__init__.py": ""},
        extra_toml='[dependency-groups]\ntest = ["sb-testkit", "pytest>=8"]\n',
    )
    changed = _paths("libs/py/sb_testkit/src/sb_testkit/__init__.py")
    assert affected_members(load_graph(workspace), changed) == ("ledger", "sb-testkit")


@pytest.mark.parametrize("config", ["ruff.toml", "pyrightconfig.json"])
def test_root_lint_and_type_config_affects_everything(repo: Path, config: str) -> None:
    assert len(affected_members(load_graph(repo), _paths(config))) == 4


def test_template_change_runs_the_member_that_tests_the_templates(
    workspace: Path, add_member
) -> None:
    """tools/templates/** belongs to no member; its tests live in sb-checks (test_templates.py),
    so a template-only change must still select sb-checks."""
    add_member("tools/checks", "sb-checks", files={"src/sb_checks/__init__.py": ""})
    add_member("tools/graph", "sb-graph", files={"src/sb_graph/__init__.py": ""})
    graph = load_graph(workspace)
    changed = _paths("tools/templates/service/template/src/{{ name }}/main.py.jinja")
    assert affected_members(graph, changed) == ("sb-checks",)


def test_scaffold_make_targets_affect_everything(repo: Path) -> None:
    assert len(affected_members(load_graph(repo), _paths("mk/scaffold.mk"))) == 4


@pytest.mark.parametrize(
    "changed",
    [
        "services/ledger/src/ledger/bootstrap.py",  # the template's drift guard compares with it
        "libs/py/sb_db/src/sb_db/uow.py",  # a generated service must still pass with the libs
    ],
)
def test_ledger_and_lib_changes_also_run_the_template_tests(
    workspace: Path, add_member, changed: str
) -> None:
    """test_templates.py (sb-checks) compares the template with services/ledger and runs the
    rendered service against libs/py, so a PR that drifts either must select sb-checks."""
    add_member("libs/py/sb_db", "sb-db", files={"src/sb_db/__init__.py": ""})
    add_member(
        "services/ledger",
        "ledger",
        deps=["sb-db"],
        files={"src/ledger/__init__.py": "import sb_db\n"},
    )
    add_member("tools/checks", "sb-checks", files={"src/sb_checks/__init__.py": ""})
    add_member("tools/graph", "sb-graph", files={"src/sb_graph/__init__.py": ""})
    assert "sb-checks" in affected_members(load_graph(workspace), _paths(changed))
