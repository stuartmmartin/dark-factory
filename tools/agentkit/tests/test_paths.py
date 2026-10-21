from pathlib import Path, PurePosixPath

from sb_agentkit.paths import repo_relative, repo_relative_lexical, repo_root_for, target_views


def test_relative_path_is_kept(tmp_path: Path) -> None:
    assert repo_relative("tach.toml", tmp_path) == PurePosixPath("tach.toml")


def test_dot_slash_is_normalized(tmp_path: Path) -> None:
    assert repo_relative("./mk/../tach.toml", tmp_path) == PurePosixPath("tach.toml")


def test_absolute_path_inside_repo_becomes_relative(tmp_path: Path) -> None:
    assert repo_relative(str(tmp_path / ".env"), tmp_path) == PurePosixPath(".env")


def test_path_outside_repo_is_none(tmp_path: Path) -> None:
    assert repo_relative("/etc/hosts", tmp_path) is None
    assert repo_relative("../elsewhere/x.py", tmp_path) is None


def test_empty_path_is_none(tmp_path: Path) -> None:
    assert repo_relative("", tmp_path) is None


def test_symlinked_root_is_resolved(tmp_path: Path) -> None:
    """A repo root reached through a symlink (e.g. macOS /tmp -> /private/tmp) must still
    match a real, already-resolved absolute path underneath it."""
    real_root = tmp_path / "real"
    real_root.mkdir()
    (real_root / "tach.toml").write_text("")
    link_root = tmp_path / "link"
    link_root.symlink_to(real_root)
    assert repo_relative(str(real_root / "tach.toml"), link_root) == PurePosixPath("tach.toml")


def test_symlink_target_is_resolved(tmp_path: Path) -> None:
    """A symlink standing in for another file resolves to what it actually points at."""
    (tmp_path / ".env").write_text("SECRET=1")
    (tmp_path / "notes.txt").symlink_to(tmp_path / ".env")
    assert repo_relative("notes.txt", tmp_path) == PurePosixPath(".env")


def test_repo_relative_lexical_does_not_follow_symlinks(tmp_path: Path) -> None:
    """The lexical view keeps the requested name, even when it is itself a symlink."""
    (tmp_path / ".env").write_text("SECRET=1")
    (tmp_path / "notes.txt").symlink_to(tmp_path / ".env")
    assert repo_relative_lexical("notes.txt", tmp_path) == PurePosixPath("notes.txt")


def _nested_worktree(root: Path) -> Path:
    worktree = root / ".claude" / "worktrees" / "w1"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: /elsewhere/.git/worktrees/w1\n")
    return worktree


def test_repo_root_for_finds_nested_worktree(tmp_path: Path) -> None:
    worktree = _nested_worktree(tmp_path)
    assert repo_root_for(worktree / "src" / "a.py", tmp_path) == worktree
    assert repo_root_for(worktree, tmp_path) == worktree


def test_repo_root_for_uses_nearest_git_marker(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    assert repo_root_for(tmp_path / "tach.toml", tmp_path / "other") == tmp_path


def test_repo_root_for_falls_back_without_marker(tmp_path: Path) -> None:
    assert repo_root_for(tmp_path / "x" / "y.py", tmp_path) == tmp_path


def test_target_views_are_relative_to_the_nested_root(tmp_path: Path) -> None:
    worktree = _nested_worktree(tmp_path)
    views = target_views(".claude/worktrees/w1/tach.toml", tmp_path)
    assert views == ((worktree, PurePosixPath("tach.toml")),)


def test_target_views_outside_any_root_are_empty(tmp_path: Path) -> None:
    assert target_views("", tmp_path) == ()
    assert target_views("/nonexistent-root-xyz/a.py", tmp_path) == ()
