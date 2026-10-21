import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from sb_agentkit.runner import Result
from sb_agentkit.session_base import ensure_session_base, read_session_base, session_base_path


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return done.stdout.strip()


def _repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "T")
    (path / "a.txt").write_text("x\n")
    _git(path, "add", ".")
    _git(path, "commit", "-q", "-m", "init")
    return path


def test_ensure_records_head_once_and_does_not_overwrite(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r")
    first = _git(repo, "rev-parse", "HEAD")
    ensure_session_base(repo, "s1")
    assert read_session_base(repo, "s1") == first
    (repo / "b.txt").write_text("y\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "second")
    ensure_session_base(repo, "s1")
    assert read_session_base(repo, "s1") == first


def test_each_session_id_has_its_own_file(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r")
    first = _git(repo, "rev-parse", "HEAD")
    ensure_session_base(repo, "s1")
    (repo / "b.txt").write_text("y\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "second")
    ensure_session_base(repo, "s2")
    assert read_session_base(repo, "s1") == first
    assert read_session_base(repo, "s2") == _git(repo, "rev-parse", "HEAD")
    assert session_base_path(repo, "s1") != session_base_path(repo, "s2")


def test_empty_or_unsafe_session_id_does_nothing(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r")
    for bad in ("", "..", "../x", "a/b"):
        ensure_session_base(repo, bad)
        assert read_session_base(repo, bad) is None
        assert session_base_path(repo, bad) is None
    assert not (repo / ".git" / "sb-agentkit").exists()


def test_not_a_git_repo_never_raises(tmp_path: Path) -> None:
    ensure_session_base(tmp_path, "s1")
    assert read_session_base(tmp_path, "s1") is None


def test_unwritable_git_dir_never_raises(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r")
    (repo / ".git" / "sb-agentkit").write_text("a file, so mkdir/write fails\n")
    ensure_session_base(repo, "s1")
    assert read_session_base(repo, "s1") is None


def test_linked_worktree_has_its_own_baseline(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r")
    worktree = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", "-b", "feat", str(worktree))
    ensure_session_base(repo, "s1")
    (worktree / "b.txt").write_text("y\n")
    _git(worktree, "add", ".")
    _git(worktree, "commit", "-q", "-m", "wt")
    assert read_session_base(worktree, "s1") is None
    ensure_session_base(worktree, "s1")
    path = session_base_path(worktree, "s1")
    assert path is not None
    assert "worktrees" in path.parts
    assert read_session_base(worktree, "s1") == _git(worktree, "rev-parse", "HEAD")
    assert read_session_base(repo, "s1") != read_session_base(worktree, "s1")


def test_non_utf8_baseline_file_reads_as_none(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r")
    ensure_session_base(repo, "s1")
    path = session_base_path(repo, "s1")
    assert path is not None
    path.write_bytes(b"\xff\xfe\x00bad")
    assert read_session_base(repo, "s1") is None


@pytest.mark.parametrize("content", ["not-a-sha\n", "-D\n", "\n", "abc\n"])
def test_baseline_that_is_not_a_full_sha_reads_as_none(tmp_path: Path, content: str) -> None:
    repo = _repo(tmp_path / "r")
    ensure_session_base(repo, "s1")
    path = session_base_path(repo, "s1")
    assert path is not None
    path.write_text(content)
    assert read_session_base(repo, "s1") is None


def test_runner_failures_are_swallowed(tmp_path: Path) -> None:
    def boom(argv: Sequence[str], cwd: Path) -> Result:
        raise subprocess.TimeoutExpired(list(argv), 1)

    ensure_session_base(tmp_path, "s1", boom)
    assert read_session_base(tmp_path, "s1", boom) is None


def test_write_is_atomic_and_leaves_no_temp_files(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r")
    ensure_session_base(repo, "s1")
    ensure_session_base(repo, "s1")
    names = sorted(p.name for p in (repo / ".git" / "sb-agentkit").iterdir())
    assert names == ["session-base-s1"]
