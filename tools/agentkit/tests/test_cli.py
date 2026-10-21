import io
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from sb_agentkit import cli
from sb_agentkit.cli import main
from sb_agentkit.hookio import Decision
from sb_agentkit.runner import Result, subprocess_runner


def _stdin(payload: object) -> io.StringIO:
    return io.StringIO(payload if isinstance(payload, str) else json.dumps(payload))


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _repo_with_service_change(tmp_path: Path) -> Path:
    _git(["init", "-q", "-b", "main"], tmp_path)
    _git(["config", "user.email", "test@example.com"], tmp_path)
    _git(["config", "user.name", "Test"], tmp_path)
    (tmp_path / "README.md").write_text("hello\n")
    _git(["add", "."], tmp_path)
    _git(["commit", "-q", "-m", "init"], tmp_path)
    _git(["checkout", "-q", "-b", "feature"], tmp_path)
    service_dir = tmp_path / "services" / "ledger" / "src" / "ledger"
    service_dir.mkdir(parents=True)
    (service_dir / "post.py").write_text("x = 1\n")
    _git(["add", "."], tmp_path)
    _git(["commit", "-q", "-m", "add service file"], tmp_path)
    return tmp_path


def test_pre_edit_blocks_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    payload = {"tool_name": "Write", "tool_input": {"file_path": ".env"}, "cwd": str(tmp_path)}
    assert main(["hook", "pre-edit"], stdin=_stdin(payload)) == 2
    assert ".env" in capsys.readouterr().err


def test_garbage_payload_allows_with_warning(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["hook", "pre-edit"], stdin=_stdin("not json")) == 0
    assert "unreadable hook payload" in capsys.readouterr().err


def test_pre_read_blocks_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    payload = {"tool_name": "Read", "tool_input": {"file_path": ".env"}, "cwd": str(tmp_path)}
    assert main(["hook", "pre-read"], stdin=_stdin(payload)) == 2
    assert ".env" in capsys.readouterr().err


def test_review_triage_success_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo_with_service_change(tmp_path)
    assert main(["review-triage", "--base", "main", "--root", str(repo)]) == 0
    matrix = json.loads(capsys.readouterr().out)
    names = [entry["reviewer"] for entry in matrix["include"]]
    assert "architecture" in names


def test_review_triage_missing_base_exits_2() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["review-triage"])
    assert exc_info.value.code == 2


def test_review_triage_bad_base_ref_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo_with_service_change(tmp_path)
    result = main(["review-triage", "--base", "does-not-exist", "--root", str(repo)])
    assert result == 2
    assert "git diff failed for base" in capsys.readouterr().err


def test_guardrail_diff_lists_changed_guardrails_and_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("SB_ALLOW_GUARDRAIL_EDITS", raising=False)
    repo = _repo_with_service_change(tmp_path)
    (repo / "ruff.toml").write_text("loosened\n")
    assert main(["guardrail-diff", "--base", "main", "--root", str(repo)]) == 1
    assert capsys.readouterr().out.splitlines() == ["ruff.toml"]


def test_guardrail_diff_clean_exits_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("SB_ALLOW_GUARDRAIL_EDITS", raising=False)
    repo = _repo_with_service_change(tmp_path)
    assert main(["guardrail-diff", "--base", "main", "--root", str(repo)]) == 0
    assert capsys.readouterr().out == ""


def test_guardrail_diff_outside_git_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["guardrail-diff", "--root", str(tmp_path)]) == 2
    assert "guardrail-diff" in capsys.readouterr().err


def test_informational_hook_result_goes_to_stdout_as_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "check_post_edit", lambda *_: Decision.inform("fyi"))
    payload = {"hook_event_name": "PostToolUse", "tool_input": {"file_path": "a.py"}}
    assert main(["hook", "post-edit"], stdin=_stdin(payload)) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"] == {"hookEventName": "PostToolUse", "additionalContext": "fyi"}


def test_repeated_failed_stop_emits_user_visible_system_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo_with_service_change(tmp_path)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))

    def run(argv: Sequence[str], cwd: Path) -> Result:
        if argv[:2] == ["make", "check-fast"]:
            return Result(1, "check failed")
        return subprocess_runner(argv, cwd)

    monkeypatch.setattr(cli, "subprocess_runner", run)
    payload = {"hook_event_name": "Stop", "cwd": str(repo), "stop_hook_active": True}
    assert main(["hook", "stop"], stdin=_stdin(payload)) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "systemMessage": (
            "BLOCKED: completion verification has not passed. Automatic repair has stopped. "
            "Human review is required; this task is not verified.\n"
            "`make check-fast` fails on the current inputs. Fix these before finishing, "
            "or report a pre-existing/out-of-scope failure as BLOCKED:\ncheck failed"
        )
    }


def _bash_payload(repo: Path, session_id: str) -> dict[str, object]:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "ls"},
        "cwd": str(repo),
        "session_id": session_id,
    }


def _head(repo: Path) -> str:
    done = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


def test_first_pre_bash_call_records_the_session_baseline_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo_with_service_change(tmp_path)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    base = repo / ".git" / "sb-agentkit" / "session-base-s1"
    first = _head(repo)
    assert main(["hook", "pre-bash"], stdin=_stdin(_bash_payload(repo, "s1"))) == 0
    assert base.read_text().strip() == first
    (repo / "x.txt").write_text("x\n")
    _git(["add", "."], repo)
    _git(["commit", "-q", "-m", "later"], repo)
    assert main(["hook", "pre-bash"], stdin=_stdin(_bash_payload(repo, "s1"))) == 0
    assert base.read_text().strip() == first
    assert main(["hook", "pre-bash"], stdin=_stdin(_bash_payload(repo, "s2"))) == 0
    assert (repo / ".git" / "sb-agentkit" / "session-base-s2").read_text().strip() == _head(repo)


@pytest.mark.parametrize("hook", ["pre-edit", "pre-read"])
def test_pre_edit_and_pre_read_also_record_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hook: str
) -> None:
    repo = _repo_with_service_change(tmp_path)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    payload = _bash_payload(repo, "s1") | {"tool_input": {"file_path": "README.md"}}
    main(["hook", hook], stdin=_stdin(payload))
    assert (repo / ".git" / "sb-agentkit" / "session-base-s1").is_file()


def test_post_edit_and_stop_do_not_record_a_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo_with_service_change(tmp_path)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    main(["hook", "post-edit"], stdin=_stdin(_bash_payload(repo, "s1")))
    assert not (repo / ".git" / "sb-agentkit").exists()


def test_missing_session_id_records_nothing_and_does_not_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo_with_service_change(tmp_path)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    payload = _bash_payload(repo, "")
    del payload["session_id"]
    assert main(["hook", "pre-bash"], stdin=_stdin(payload)) == 0
    assert not (repo / ".git" / "sb-agentkit").exists()
