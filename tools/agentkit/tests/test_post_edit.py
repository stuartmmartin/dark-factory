import json
from collections.abc import Sequence
from pathlib import Path

from sb_agentkit.hookio import HookInput
from sb_agentkit.post_edit import check_post_edit
from sb_agentkit.runner import Result


class RecordingRunner:
    """Test double for Runner: records argv, returns scripted results by tool name."""

    def __init__(self, results: dict[str, Result] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.cwds: list[Path] = []
        self.results = results or {}

    def __call__(self, argv: Sequence[str], cwd: Path) -> Result:
        self.calls.append(list(argv))
        self.cwds.append(cwd)
        tool = next((name for name in ("ruff", "pyright") if any(name in a for a in argv)), "")
        key = ("ruff --fix" if "--fix" in argv else f"ruff {argv[-2]}") if tool == "ruff" else tool
        return self.results.get(key, Result(0, ""))


def _edit(path: str) -> HookInput:
    raw = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": path}})
    parsed = HookInput.parse(raw, default_cwd=Path("/repo"))
    assert parsed is not None
    return parsed


def test_python_file_gets_ruff_fix_format_and_pyright(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    run = RecordingRunner()
    assert not check_post_edit(_edit("a.py"), tmp_path, run).block
    joined = [" ".join(call) for call in run.calls]
    assert any("ruff check" in c and "--fix" in c for c in joined)
    assert any("ruff format" in c for c in joined)
    assert any("pyright" in c for c in joined)
    assert all(c.endswith("a.py") for c in joined)


def test_pyright_errors_are_fed_back(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x: int = 'a'\n")
    run = RecordingRunner({"pyright": Result(1, "a.py:1:10 - error: str is not int")})
    decision = check_post_edit(_edit("a.py"), tmp_path, run)
    assert decision.block
    assert "str is not int" in decision.message


def test_unfixable_ruff_errors_are_fed_back(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("import os\n")
    run = RecordingRunner({"ruff --fix": Result(1, "a.py:1:8: F401 unused")})
    decision = check_post_edit(_edit("a.py"), tmp_path, run)
    assert decision.block
    assert "F401" in decision.message


def test_non_python_and_missing_files_are_skipped(tmp_path: Path) -> None:
    run = RecordingRunner()
    assert not check_post_edit(_edit("README.md"), tmp_path, run).block
    assert not check_post_edit(_edit("gone.py"), tmp_path, run).block
    assert not check_post_edit(_edit("/elsewhere/x.py"), tmp_path, run).block
    assert run.calls == []


def test_ruff_fix_never_deletes_unused_imports_or_commented_code(tmp_path: Path) -> None:
    """A test-first edit adds the import before the code that uses it; don't delete it."""
    (tmp_path / "a.py").write_text("import os\n")
    run = RecordingRunner()
    check_post_edit(_edit("a.py"), tmp_path, run)
    fix_call = next(c for c in run.calls if "--fix" in c)
    assert fix_call[fix_call.index("--unfixable") + 1] == "F401,ERA001"


def test_pyright_errors_in_tests_are_informational(tmp_path: Path) -> None:
    """RED phase of TDD: a test importing a not-yet-written symbol must not block the edit."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("from a import missing\n")
    run = RecordingRunner({"pyright": Result(1, 'test_a.py:1:15 - error: "missing" is unknown')})
    decision = check_post_edit(_edit("tests/test_a.py"), tmp_path, run)
    assert not decision.block
    assert '"missing" is unknown' in decision.message
    assert "informational" in decision.message


def test_ruff_errors_in_tests_still_block(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("x = 1\n")
    run = RecordingRunner({"ruff --fix": Result(1, "test_a.py:1:1: E999 boom")})
    assert check_post_edit(_edit("tests/test_a.py"), tmp_path, run).block


def test_pyright_errors_in_src_still_block(tmp_path: Path) -> None:
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / "pkg" / "a.py").write_text("x: int = 'a'\n")
    run = RecordingRunner({"pyright": Result(1, "a.py:1:10 - error: str is not int")})
    assert check_post_edit(_edit("src/pkg/a.py"), tmp_path, run).block


def test_nested_worktree_file_is_checked_from_its_own_root(tmp_path: Path) -> None:
    worktree = tmp_path / ".claude" / "worktrees" / "w1"
    (worktree / "src").mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: /elsewhere\n")
    (worktree / "src" / "a.py").write_text("x = 1\n")
    run = RecordingRunner()
    check_post_edit(_edit(str(worktree / "src" / "a.py")), tmp_path, run)
    assert run.cwds
    assert set(run.cwds) == {worktree}
    assert all(call[-1] == "src/a.py" for call in run.calls)


def test_ruff_always_uses_the_root_config_explicitly(tmp_path: Path) -> None:
    """A member pyproject.toml must not shadow ruff.toml through config discovery."""
    (tmp_path / "a.py").write_text("x = 1\n")
    run = RecordingRunner()
    check_post_edit(_edit("a.py"), tmp_path, run)
    ruff_calls = [c for c in run.calls if "ruff" in c or any(a.endswith("/ruff") for a in c)]
    assert len(ruff_calls) == 2
    for call in ruff_calls:
        assert call[call.index("--config") + 1] == "ruff.toml"
