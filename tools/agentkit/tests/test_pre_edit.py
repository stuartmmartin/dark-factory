import json
from pathlib import Path

import pytest

from sb_agentkit.hookio import HookInput
from sb_agentkit.pre_edit import check_pre_edit


@pytest.mark.parametrize(
    "file_path", [".env", "services/ledger/.env", ".env.local", ".env.production"]
)
def test_blocks_secret_files(repo: Path, edit_input, base, file_path: str) -> None:
    decision = check_pre_edit(edit_input(file_path), repo, base(), env={})
    assert decision.block
    assert ".env.example" in decision.message


def test_secret_block_has_no_env_override(repo: Path, edit_input, base) -> None:
    env = {"SB_ALLOW_GUARDRAIL_EDITS": "1"}
    assert check_pre_edit(edit_input(".env"), repo, base(), env=env).block


def test_env_example_is_allowed(repo: Path, edit_input, base) -> None:
    assert not check_pre_edit(edit_input(".env.example"), repo, base(), env={}).block


def test_absolute_secret_path_is_caught(repo: Path, edit_input, base) -> None:
    assert check_pre_edit(edit_input(str(repo / ".env")), repo, base(), env={}).block


@pytest.mark.parametrize(
    "file_path",
    [
        "tach.toml",
        ".importlinter",
        "tools/checks/allowlist.toml",
        ".claude/settings.json",
        ".github/CODEOWNERS",
        ".github/workflows/ci.yml",
        "tools/agentkit/src/sb_agentkit/pre_edit.py",
    ],
)
def test_blocks_guardrail_files(repo: Path, edit_input, base, file_path: str) -> None:
    decision = check_pre_edit(edit_input(file_path), repo, base(), env={})
    assert decision.block
    assert "human-owned" in decision.message


def test_dot_slash_guardrail_path_is_caught(repo: Path, edit_input, base) -> None:
    assert check_pre_edit(edit_input("./tach.toml"), repo, base(), env={}).block


def test_guardrail_override_env_allows(repo: Path, edit_input, base) -> None:
    env = {"SB_ALLOW_GUARDRAIL_EDITS": "1"}
    assert not check_pre_edit(edit_input("tach.toml"), repo, base(), env=env).block


def test_blocks_edit_of_merged_migration(repo: Path, edit_input, base) -> None:
    rel = "services/ledger/migrations/versions/0001_init.py"
    decision = check_pre_edit(edit_input(rel), repo, base({rel}), env={})
    assert decision.block
    assert "new revision" in decision.message


def test_allows_new_unmerged_migration(repo: Path, edit_input, base) -> None:
    rel = "services/ledger/migrations/versions/0002_add.py"
    assert not check_pre_edit(edit_input(rel), repo, base(), env={}).block


def test_blocks_edit_of_merged_migration_case_insensitively(repo: Path, edit_input, base) -> None:
    rel = "SERVICES/ledger/MIGRATIONS/versions/0001_init.PY"
    decision = check_pre_edit(edit_input(rel), repo, base({rel}), env={})
    assert decision.block
    assert "new revision" in decision.message


def test_ordinary_file_and_outside_repo_are_allowed(repo: Path, edit_input, base) -> None:
    assert not check_pre_edit(edit_input("services/x/src/x/a.py"), repo, base(), env={}).block
    assert not check_pre_edit(edit_input("/tmp/scratch.py"), repo, base(), env={}).block


def test_input_without_file_path_is_allowed(repo: Path, edit_input, base) -> None:
    assert not check_pre_edit(edit_input(""), repo, base(), env={}).block


@pytest.mark.parametrize(
    "file_path", [".ENV", "services/ledger/.ENV", ".Env.Local", ".ENV.PRODUCTION"]
)
def test_blocks_secret_files_case_insensitively(
    repo: Path, edit_input, base, file_path: str
) -> None:
    assert check_pre_edit(edit_input(file_path), repo, base(), env={}).block


@pytest.mark.parametrize(
    "file_path",
    [
        "TACH.TOML",
        ".Importlinter",
        ".GITHUB/CODEOWNERS",
        ".github/WORKFLOWS/ci.yml",
        "TOOLS/agentkit/SRC/sb_agentkit/pre_edit.py",
    ],
)
def test_blocks_guardrail_files_case_insensitively(
    repo: Path, edit_input, base, file_path: str
) -> None:
    decision = check_pre_edit(edit_input(file_path), repo, base(), env={})
    assert decision.block
    assert "human-owned" in decision.message


def test_symlinked_root_secret_is_still_blocked(tmp_path: Path, base) -> None:
    """A repo root reached via a symlink must not make a real secret file look external."""
    real_root = tmp_path / "real"
    real_root.mkdir()
    link_root = tmp_path / "link"
    link_root.symlink_to(real_root)
    raw = json.dumps(
        {
            "tool_name": "Edit",
            "tool_input": {"file_path": str(real_root / ".env")},
            "cwd": str(link_root),
        }
    )
    inp = HookInput.parse(raw, default_cwd=link_root)
    assert inp is not None
    assert check_pre_edit(inp, link_root, base(), env={}).block


def test_symlink_to_secret_file_is_blocked(repo: Path, edit_input, base) -> None:
    """A symlink whose target is a secret file must not launder a write to it."""
    (repo / ".env").write_text("SECRET=1")
    (repo / "notes.txt").symlink_to(repo / ".env")
    decision = check_pre_edit(edit_input("notes.txt"), repo, base(), env={})
    assert decision.block
    assert ".env" in decision.message


def test_symlink_to_guardrail_file_is_blocked(repo: Path, edit_input, base) -> None:
    """A symlink whose target is a guardrail file must not launder a write to it."""
    (repo / "tach.toml").write_text("")
    (repo / "innocuous.py").symlink_to(repo / "tach.toml")
    decision = check_pre_edit(edit_input("innocuous.py"), repo, base(), env={})
    assert decision.block
    assert "human-owned" in decision.message


@pytest.mark.parametrize(
    "file_path",
    [
        ".claude/settings.local.json",
        ".claude/skills/code-review/reviewer-prompt.md",
        ".claude/agents/code-reviewer.md",
        ".github/scripts/check-override.sh",
        ".git/hooks/pre-commit",
        "tools/checks/src/sb_checks/checks/no_float.py",
        "tools/agentkit/tests/test_pre_edit.py",
        ".pre-commit-config.yaml",
        "conftest.py",
        "docs/conventions/testing.md",
        "ruff.toml",
        "pyrightconfig.json",
    ],
)
def test_blocks_extended_guardrails(repo: Path, edit_input, base, file_path: str) -> None:
    decision = check_pre_edit(edit_input(file_path), repo, base(), env={})
    assert decision.block
    assert "human-owned" in decision.message


@pytest.mark.parametrize(
    "file_path",
    ["pyproject.toml", "Makefile", "mk/python.mk", "mk/quality.mk", ".claude/rules/tests.md"],
)
def test_daily_work_files_stay_editable(repo: Path, edit_input, base, file_path: str) -> None:
    assert not check_pre_edit(edit_input(file_path), repo, base(), env={}).block


def test_guardrail_deny_message_names_the_override(repo: Path, edit_input, base) -> None:
    message = check_pre_edit(edit_input("tach.toml"), repo, base(), env={}).message
    assert "SB_ALLOW_GUARDRAIL_EDITS" in message
    assert "a human sets it when launching Claude" in message
    assert "docs/agents/hooks.md" in message


def test_scoped_override_allows_only_the_listed_guardrail(repo: Path, edit_input, base) -> None:
    env = {"SB_ALLOW_GUARDRAIL_EDITS": "tach.toml,.github/workflows/**"}
    assert not check_pre_edit(edit_input("tach.toml"), repo, base(), env=env).block
    assert not check_pre_edit(edit_input(".github/workflows/ci.yml"), repo, base(), env=env).block
    assert check_pre_edit(edit_input(".importlinter"), repo, base(), env=env).block
    assert check_pre_edit(edit_input(".github/CODEOWNERS"), repo, base(), env=env).block


def test_blocks_user_level_claude_config(tmp_path: Path, base) -> None:
    repo, home = tmp_path / "repo", tmp_path / "home"
    repo.mkdir()
    (home / ".claude").mkdir(parents=True)
    raw = json.dumps(
        {"tool_name": "Write", "tool_input": {"file_path": str(home / ".claude/settings.json")}}
    )
    inp = HookInput.parse(raw, default_cwd=repo)
    assert inp is not None
    decision = check_pre_edit(inp, repo, base(), env={}, home=home)
    assert decision.block
    assert "~/.claude" in decision.message
    assert check_pre_edit(
        inp, repo, base(), env={"SB_ALLOW_GUARDRAIL_EDITS": "tach.toml"}, home=home
    ).block
    assert not check_pre_edit(
        inp, repo, base(), env={"SB_ALLOW_GUARDRAIL_EDITS": "1"}, home=home
    ).block


def _nested_worktree(repo: Path) -> Path:
    worktree = repo / ".claude" / "worktrees" / "w1"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: /elsewhere/.git/worktrees/w1\n")
    return worktree


def test_guardrail_in_nested_worktree_is_blocked(repo: Path, edit_input, base) -> None:
    worktree = _nested_worktree(repo)
    for target in (".claude/worktrees/w1/tach.toml", str(worktree / ".github/workflows/ci.yml")):
        decision = check_pre_edit(edit_input(target), repo, base(), env={})
        assert decision.block, target
        assert "human-owned" in decision.message


def test_merged_migration_in_nested_worktree_is_checked_against_its_root(
    repo: Path, edit_input, base
) -> None:
    _nested_worktree(repo)
    rel = "services/ledger/migrations/versions/0001_init.py"
    decision = check_pre_edit(edit_input(f".claude/worktrees/w1/{rel}"), repo, base({rel}), env={})
    assert decision.block
    assert "new revision" in decision.message
