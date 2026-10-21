import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

from sb_agentkit.hookio import HookInput
from sb_agentkit.runner import Result, subprocess_runner
from sb_agentkit.session_base import ensure_session_base
from sb_agentkit.stop import check_stop, working_state


class ScriptedRunner:
    """Scripted git + make. `guardrails` is what `git diff --name-only <base>` reports."""

    def __init__(self, status: str, check: Result, guardrails: str = "") -> None:
        self.status = status
        self.check = check
        self.guardrails = guardrails
        self.calls: list[list[str]] = []
        self.cwds: list[Path] = []

    def __call__(self, argv: Sequence[str], cwd: Path) -> Result:
        self.calls.append(list(argv))
        self.cwds.append(cwd)
        if argv[:2] == ["git", "status"]:
            return Result(0, self.status)
        if argv[:2] == ["git", "rev-parse"]:
            return Result(1, "")
        if argv[:2] == ["git", "merge-base"]:
            return Result(0, "abc123\n")
        if argv[:2] == ["git", "diff"]:
            paths = self.guardrails.split()
            for line in self.status.splitlines():
                paths.extend(line[3:].split(" -> "))
            return Result(0, "\0".join(paths))
        if argv[:2] == ["git", "ls-files"]:
            return Result(0, "")
        return self.check

    def make_calls(self) -> list[list[str]]:
        return [c for c in self.calls if c[:1] == ["make"]]


def _stop(active: bool = False, cwd: Path | None = None) -> HookInput:
    payload: dict[str, object] = {"stop_hook_active": active}
    if cwd is not None:
        payload["cwd"] = str(cwd)
    parsed = HookInput.parse(json.dumps(payload), default_cwd=Path("/r"))
    assert parsed is not None
    return parsed


def test_active_stop_hook_escalates_failed_verification(tmp_path: Path) -> None:
    run = ScriptedRunner(" M a.py\n", Result(2, "boom"))
    decision = check_stop(_stop(active=True), tmp_path, run, env={})
    assert not decision.block
    assert "BLOCKED" in decision.message
    assert run.make_calls() == [["make", "check-fast", "BASE=abc123"]]


def test_clean_tree_skips_checks(tmp_path: Path) -> None:
    run = ScriptedRunner("", Result(2, "boom"))
    assert not check_stop(_stop(), tmp_path, run, env={}).block
    assert run.make_calls() == []


def test_docs_only_change_still_checks_documentation(tmp_path: Path) -> None:
    run = ScriptedRunner(" M docs/README.md\n?? notes.md\n", Result(0, "ok"))
    assert not check_stop(_stop(), tmp_path, run, env={}).block
    assert run.make_calls() == [["make", "check-fast", "BASE=abc123"]]


def test_python_change_runs_check_fast_and_passes(tmp_path: Path) -> None:
    run = ScriptedRunner(" M tools/x/src/x/a.py\n", Result(0, "ok"))
    assert not check_stop(_stop(), tmp_path, run, env={}).block
    assert run.calls[-1] == ["make", "check-fast", "BASE=abc123"]


def test_failing_check_fast_blocks_with_tail_of_output(tmp_path: Path) -> None:
    output = "\n".join(f"line {i}" for i in range(200))
    run = ScriptedRunner("?? services/s/src/s/new.py\n", Result(2, output))
    decision = check_stop(_stop(), tmp_path, run, env={})
    assert decision.block
    assert "line 199" in decision.message
    assert "line 0\n" not in decision.message
    assert "make check-fast" in decision.message


def test_renamed_python_file_counts_as_change(tmp_path: Path) -> None:
    run = ScriptedRunner("R  old.py -> new.py\n", Result(0, ""))
    check_stop(_stop(), tmp_path, run, env={})
    assert run.calls[-1] == ["make", "check-fast", "BASE=abc123"]


def test_guardrail_change_is_reported(tmp_path: Path) -> None:
    run = ScriptedRunner(" M tach.toml\n", Result(0, ""), guardrails="tach.toml src/a.py ruff.toml")
    decision = check_stop(_stop(), tmp_path, run, env={})
    assert decision.block
    assert "tach.toml" in decision.message
    assert "ruff.toml" in decision.message
    assert "src/a.py" not in decision.message
    assert "differ from the session/branch baseline" in decision.message
    assert "SB_ALLOW_GUARDRAIL_EDITS" in decision.message
    assert run.make_calls() == [["make", "check-fast", "BASE=abc123"]]


def test_overridden_guardrail_change_goes_on_to_checks(tmp_path: Path) -> None:
    run = ScriptedRunner(" M a.py\n", Result(0, "ok"), guardrails="tach.toml")
    env = {"SB_ALLOW_GUARDRAIL_EDITS": "tach.toml"}
    assert not check_stop(_stop(), tmp_path, run, env=env).block
    assert run.make_calls() == [["make", "check-fast", "BASE=abc123"]]


def test_stop_in_nested_worktree_runs_there(tmp_path: Path) -> None:
    worktree = tmp_path / ".claude" / "worktrees" / "w1"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: /elsewhere\n")
    run = ScriptedRunner(" M a.py\n", Result(0, "ok"))
    check_stop(_stop(cwd=worktree), tmp_path, run, env={})
    assert set(run.cwds) == {worktree}


def test_check_fast_failure_is_reported_even_when_guardrails_changed(tmp_path: Path) -> None:
    run = ScriptedRunner(
        " M tach.toml\n M src/a.py\n", Result(2, "FAILED test_x"), guardrails="tach.toml"
    )
    decision = check_stop(_stop(), tmp_path, run, env={})
    assert decision.block
    assert "tach.toml" in decision.message
    assert "FAILED test_x" in decision.message
    assert "make check-fast" in decision.message
    assert run.make_calls() == [["make", "check-fast", "BASE=abc123"]]


def _real_repo_with_committed_guardrail(root: Path) -> None:
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "T")
    (root / "tach.toml").write_text("a\n")
    git("add", ".")
    git("commit", "-q", "-m", "init")
    git("checkout", "-q", "-b", "feature")
    (root / "tach.toml").write_text("human change before the session\n")
    git("commit", "-q", "-am", "human")


def _stop_for(session_id: str, cwd: Path) -> HookInput:
    raw = json.dumps({"session_id": session_id, "cwd": str(cwd)})
    parsed = HookInput.parse(raw, default_cwd=cwd)
    assert parsed is not None
    return parsed


def test_stop_uses_the_baseline_of_its_own_session(tmp_path: Path) -> None:
    _real_repo_with_committed_guardrail(tmp_path)
    ensure_session_base(tmp_path, "mine")
    ensure_session_base(tmp_path, "other")
    assert not check_stop(_stop_for("mine", tmp_path), tmp_path, subprocess_runner, {}).block


def test_stop_without_a_session_baseline_falls_back_to_merge_base(tmp_path: Path) -> None:
    _real_repo_with_committed_guardrail(tmp_path)
    ensure_session_base(tmp_path, "other")
    for session_id in ("unrecorded", ""):
        decision = check_stop(_stop_for(session_id, tmp_path), tmp_path, subprocess_runner, {})
        assert decision.block
        assert "tach.toml" in decision.message


class GitDirRunner(ScriptedRunner):
    """Also answers `git rev-parse --git-dir`, where the hook keeps its last-passed marker."""

    def __init__(self, git_dir: Path, status: str, check: Result) -> None:
        super().__init__(status, check)
        self.git_dir = git_dir

    def __call__(self, argv: Sequence[str], cwd: Path) -> Result:
        if list(argv) == ["git", "rev-parse", "--git-dir"]:
            self.calls.append(list(argv))
            return Result(0, f"{self.git_dir}\n")
        return super().__call__(argv, cwd)


def _stop_in_session() -> HookInput:
    parsed = HookInput.parse(json.dumps({"session_id": "s1"}), default_cwd=Path("/r"))
    assert parsed is not None
    return parsed


def test_unchanged_state_after_a_pass_skips_check_fast(tmp_path: Path) -> None:
    """Stop fires at the end of every turn; re-running the same checks on the same tree is waste."""
    run = GitDirRunner(tmp_path / "git", " M a.py\n", Result(0, "ok"))
    for _ in range(3):
        assert not check_stop(_stop_in_session(), tmp_path, run, {}, state=lambda _: "h t1").block
    assert len(run.make_calls()) == 1


def test_a_change_after_a_pass_runs_check_fast_again(tmp_path: Path) -> None:
    run = GitDirRunner(tmp_path / "git", " M a.py\n", Result(0, "ok"))
    for tree in ("h t1", "h t2"):
        check_stop(_stop_in_session(), tmp_path, run, {}, state=lambda _, t=tree: t)
    assert len(run.make_calls()) == 2


def test_a_failed_run_is_not_remembered(tmp_path: Path) -> None:
    run = GitDirRunner(tmp_path / "git", " M a.py\n", Result(2, "boom"))
    for _ in range(2):
        assert check_stop(_stop_in_session(), tmp_path, run, {}, state=lambda _: "h t1").block
    assert len(run.make_calls()) == 2


def test_without_a_working_state_check_fast_always_runs(tmp_path: Path) -> None:
    run = GitDirRunner(tmp_path / "git", " M a.py\n", Result(0, "ok"))
    for _ in range(2):
        check_stop(_stop_in_session(), tmp_path, run, {}, state=lambda _: None)
    assert len(run.make_calls()) == 2


def test_stop_check_off_skips_check_fast_but_still_reports_guardrails(tmp_path: Path) -> None:
    run = ScriptedRunner(" M tach.toml\n", Result(2, "boom"), guardrails="tach.toml")
    decision = check_stop(_stop(), tmp_path, run, env={"SB_STOP_CHECK": "0"})
    assert decision.block
    assert "tach.toml" in decision.message
    assert "boom" not in decision.message
    assert run.make_calls() == []


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)
    return done.stdout


def test_working_state_tracks_edits_and_untracked_files(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    (tmp_path / "a.py").write_text("a\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "init")
    clean = working_state(tmp_path)
    assert clean is not None
    (tmp_path / "a.py").write_text("b\n")
    edited = working_state(tmp_path)
    assert edited not in (None, clean)
    (tmp_path / "a.py").write_text("a\n")
    assert working_state(tmp_path) == clean
    (tmp_path / "new.py").write_text("x\n")
    assert working_state(tmp_path) not in (None, clean)
    assert _git(tmp_path, "status", "--porcelain") == "?? new.py\n"  # the real index is untouched


def test_working_state_outside_a_repo_is_none(tmp_path: Path) -> None:
    assert working_state(tmp_path) is None
