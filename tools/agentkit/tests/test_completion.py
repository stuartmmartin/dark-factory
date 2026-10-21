"""Completion checks cover committed, staged, untracked and config-only session work."""

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from sb_agentkit.hookio import HookInput
from sb_agentkit.runner import Result, subprocess_runner
from sb_agentkit.session_base import ensure_session_base
from sb_agentkit.stop import check_stop


def git(root: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "README.md").write_text("baseline\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "baseline")
    ensure_session_base(tmp_path, "session")
    return tmp_path


class GateRunner:
    def __init__(self, succeeds: bool = True) -> None:
        self.succeeds = succeeds
        self.checks: list[list[str]] = []

    def __call__(self, argv: Sequence[str], cwd: Path) -> Result:
        if argv[0] == "make":
            self.checks.append(list(argv))
            return Result(0 if self.succeeds else 1, "check output")
        return subprocess_runner(argv, cwd)


def stop(root: Path, active: bool = False) -> HookInput:
    inp = HookInput.parse(
        json.dumps(
            {
                "cwd": str(root),
                "session_id": "session",
                "stop_hook_active": active,
            }
        ),
        default_cwd=root,
    )
    assert inp is not None
    return inp


@pytest.mark.parametrize("path", ["src/new.py", "pyproject.toml", "new/nested/config.yaml"])
@pytest.mark.parametrize("state", ["untracked", "staged", "committed"])
def test_all_session_inputs_require_verification(repo: Path, path: str, state: str) -> None:
    file = repo / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text("changed\n")
    if state != "untracked":
        git(repo, "add", ".")
    if state == "committed":
        git(repo, "commit", "-qm", "session change")
    runner = GateRunner()
    assert not check_stop(stop(repo), repo, runner, {}).block
    assert len(runner.checks) == 1
    assert runner.checks[0][:2] == ["make", "check-fast"]
    assert runner.checks[0][2].startswith("BASE=")


def test_git_inspection_failure_blocks(tmp_path: Path) -> None:
    decision = check_stop(stop(tmp_path), tmp_path, GateRunner(), {})
    assert decision.block
    assert "inspect" in decision.message.lower()


def test_repeat_stop_reports_blocked_not_verified(repo: Path) -> None:
    (repo / "new.py").write_text("x = 1\n")
    runner = GateRunner(succeeds=False)
    first = check_stop(stop(repo), repo, runner, {})
    assert first.block
    repeated = check_stop(stop(repo, active=True), repo, runner, {})
    assert not repeated.block  # bounded repair loop: permit escalation, not a success claim
    assert "BLOCKED" in repeated.message
    assert len(runner.checks) == 2


def test_repaired_change_can_pass_on_repeat_stop(repo: Path) -> None:
    (repo / "new.py").write_text("x = 1\n")
    runner = GateRunner()
    decision = check_stop(stop(repo, active=True), repo, runner, {})
    assert not decision.block
    assert not decision.message
    assert len(runner.checks) == 1
