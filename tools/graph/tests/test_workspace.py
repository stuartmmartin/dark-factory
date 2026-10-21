from pathlib import Path, PurePosixPath

import pytest

from sb_graph.workspace import Member, WorkspaceError, discover_members, normalize


def test_normalize_follows_pep_503() -> None:
    assert normalize("SB_Kernel.Core") == "sb-kernel-core"


def test_discovers_members_sorted_with_kind_and_internal_deps(workspace: Path, add_member) -> None:
    add_member("services/ledger", "ledger", deps=["SB_Kernel>=0.1", "fastapi>=0.115"])
    add_member("libs/py/sb_kernel", "sb-kernel")
    assert discover_members(workspace) == (
        Member(
            "ledger",
            "ledger",
            PurePosixPath("services/ledger"),
            "service",
            "python",
            ("sb-kernel",),
        ),
        Member("sb-kernel", "sb_kernel", PurePosixPath("libs/py/sb_kernel"), "lib", "python", ()),
    )


def test_import_name_can_be_overridden(workspace: Path, add_member) -> None:
    add_member("tools/x", "sb-x", extra_toml='[tool.sb]\nimport-name = "xtool"\n')
    [member] = discover_members(workspace)
    assert member.import_name == "xtool"


def test_directories_without_pyproject_are_ignored(workspace: Path) -> None:
    (workspace / "services" / "empty").mkdir(parents=True)
    assert discover_members(workspace) == ()


def test_member_without_project_name_raises_naming_the_file(workspace: Path) -> None:
    directory = workspace / "tools" / "bad"
    directory.mkdir(parents=True)
    (directory / "pyproject.toml").write_text("[project]\nversion = '1'\n")
    with pytest.raises(WorkspaceError, match="tools/bad/pyproject.toml"):  # noqa: RUF043
        discover_members(workspace)


def test_member_outside_known_top_dirs_raises(workspace: Path, add_member) -> None:
    (workspace / "pyproject.toml").write_text('[tool.uv.workspace]\nmembers = ["weird/*"]\n')
    add_member("weird/x", "x")
    with pytest.raises(WorkspaceError, match="weird/x"):
        discover_members(workspace)


def test_missing_root_pyproject_raises_workspace_error(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError, match="not found; run from the repo root or pass --root"):
        discover_members(tmp_path)


def test_dependency_group_members_are_test_declared(workspace: Path, add_member) -> None:
    add_member("libs/py/sb_testkit", "sb-testkit")
    add_member("libs/py/sb_kernel", "sb-kernel")
    add_member(
        "services/ledger",
        "ledger",
        deps=["sb-kernel"],
        extra_toml=(
            "[dependency-groups]\n"
            'test = ["SB_Testkit>=0.1", "pytest>=8", {include-group = "lint"}]\n'
            'lint = ["ruff", "ledger"]\n'
        ),
    )
    ledger = next(m for m in discover_members(workspace) if m.name == "ledger")
    assert ledger.declared == ("sb-kernel",)
    assert ledger.test_declared == ("sb-testkit",)


def test_workspace_exclude_globs_are_skipped(workspace: Path, add_member) -> None:
    (workspace / "pyproject.toml").write_text(
        '[tool.uv.workspace]\nmembers = ["services/*"]\nexclude = ["services/scratch*"]\n'
    )
    add_member("services/ledger", "ledger")
    add_member("services/scratchpad", "scratchpad")
    assert [m.name for m in discover_members(workspace)] == ["ledger"]
