import subprocess
from pathlib import Path, PurePosixPath

import pytest

from sb_agentkit.guardrail_diff import GitError, changed_guardrails
from sb_agentkit.session_base import ensure_session_base, read_session_base


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _write(root: Path, rel: str, text: str = "x\n") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    for rel in ("README.md", "tach.toml", "ruff.toml", "pyproject.toml", "src/a.py"):
        _write(tmp_path, rel)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "init")
    _git(tmp_path, "checkout", "-q", "-b", "feature")
    return tmp_path


def _paths(*names: str) -> list[PurePosixPath]:
    return [PurePosixPath(n) for n in names]


def test_clean_branch_has_no_guardrail_changes(repo: Path) -> None:
    assert changed_guardrails(repo, "main", env={}) == []


def test_committed_uncommitted_and_untracked_guardrail_changes(repo: Path) -> None:
    _write(repo, "tach.toml", "changed\n")
    _git(repo, "commit", "-q", "-am", "loosen tach")
    _write(repo, "ruff.toml", "changed\n")  # unstaged
    _write(repo, ".github/workflows/new.yml")  # untracked
    _write(repo, "src/a.py", "changed\n")
    _write(repo, "pyproject.toml", "changed\n")
    assert changed_guardrails(repo, "main", env={}) == _paths(
        ".github/workflows/new.yml", "ruff.toml", "tach.toml"
    )


def test_deleting_or_renaming_a_guardrail_reports_it(repo: Path) -> None:
    _git(repo, "mv", "tach.toml", "notes.toml")
    _git(repo, "rm", "-q", "ruff.toml")
    assert changed_guardrails(repo, "main", env={}) == _paths("ruff.toml", "tach.toml")


def test_override_one_hides_everything(repo: Path) -> None:
    _write(repo, "tach.toml", "changed\n")
    assert changed_guardrails(repo, "main", env={"SB_ALLOW_GUARDRAIL_EDITS": "1"}) == []


def test_scoped_override_hides_only_listed_paths(repo: Path) -> None:
    _write(repo, "tach.toml", "changed\n")
    _write(repo, "ruff.toml", "changed\n")
    env = {"SB_ALLOW_GUARDRAIL_EDITS": "tach.toml"}
    assert changed_guardrails(repo, "main", env=env) == _paths("ruff.toml")


def test_default_base_is_main_without_origin(repo: Path) -> None:
    _write(repo, "tach.toml", "changed\n")
    _git(repo, "commit", "-q", "-am", "loosen tach")
    assert changed_guardrails(repo, env={}) == _paths("tach.toml")


def test_unknown_base_fails_closed_instead_of_ignoring_committed_changes(repo: Path) -> None:
    _write(repo, "ruff.toml", "changed\n")
    with pytest.raises(GitError, match="merge-base"):
        changed_guardrails(repo, "does-not-exist", env={})


def test_not_a_git_repo_raises(tmp_path: Path) -> None:
    with pytest.raises(GitError):
        changed_guardrails(tmp_path, "main", env={})


def test_guardrail_committed_before_session_base_is_not_flagged(repo: Path) -> None:
    _write(repo, "tach.toml", "human change before the session\n")
    _git(repo, "commit", "-q", "-am", "human loosens tach")
    ensure_session_base(repo, "s1")
    assert changed_guardrails(repo, "main", env={}, session_id="s1") == []


def test_guardrail_changed_after_session_base_is_flagged(repo: Path) -> None:
    ensure_session_base(repo, "s1")
    _write(repo, "tach.toml", "changed\n")
    _git(repo, "commit", "-q", "-am", "agent loosens tach")
    _write(repo, "ruff.toml", "changed\n")
    assert changed_guardrails(repo, "main", env={}, session_id="s1") == _paths(
        "ruff.toml", "tach.toml"
    )


def test_missing_session_base_falls_back_to_merge_base(repo: Path) -> None:
    _write(repo, "tach.toml", "changed\n")
    _git(repo, "commit", "-q", "-am", "loosen tach")
    assert read_session_base(repo, "s1") is None
    assert changed_guardrails(repo, "main", env={}) == _paths("tach.toml")


def test_another_sessions_baseline_and_empty_id_are_ignored(repo: Path) -> None:
    _write(repo, "tach.toml", "human change before the session\n")
    _git(repo, "commit", "-q", "-am", "human loosens tach")
    ensure_session_base(repo, "other")
    assert changed_guardrails(repo, "main", env={}, session_id="s1") == _paths("tach.toml")
    assert changed_guardrails(repo, "main", env={}, session_id="") == _paths("tach.toml")


@pytest.mark.parametrize("bogus", ["0" * 40, "f" * 40])
def test_unreachable_baseline_commit_falls_back_to_merge_base(repo: Path, bogus: str) -> None:
    _write(repo, "tach.toml", "changed\n")
    _git(repo, "commit", "-q", "-am", "loosen tach")
    ensure_session_base(repo, "s1")
    path = repo / ".git" / "sb-agentkit" / "session-base-s1"
    path.write_text(bogus + "\n")
    assert changed_guardrails(repo, "main", env={}, session_id="s1") == _paths("tach.toml")
