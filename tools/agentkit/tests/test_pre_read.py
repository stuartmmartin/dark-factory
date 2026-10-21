import json
from pathlib import Path

import pytest

from sb_agentkit.hookio import HookInput
from sb_agentkit.pre_read import check_pre_read


def test_blocks_env_staging(repo: Path, edit_input) -> None:
    decision = check_pre_read(edit_input(".env.staging", tool="Read"), repo)
    assert decision.block
    assert ".env.example" in decision.message


def test_blocks_nested_env_local(repo: Path, edit_input) -> None:
    decision = check_pre_read(edit_input("services/x/.env.local", tool="Read"), repo)
    assert decision.block


def test_env_example_is_allowed(repo: Path, edit_input) -> None:
    assert not check_pre_read(edit_input(".env.example", tool="Read"), repo).block


def test_guardrail_file_is_allowed(repo: Path, edit_input) -> None:
    """Guardrail files and migrations stay readable through Read; only secrets are blocked."""
    assert not check_pre_read(edit_input("tach.toml", tool="Read"), repo).block


def test_migration_file_is_allowed(repo: Path, edit_input) -> None:
    rel = "services/ledger/migrations/versions/0001_init.py"
    assert not check_pre_read(edit_input(rel, tool="Read"), repo).block


def test_symlink_to_secret_file_is_blocked(repo: Path, edit_input) -> None:
    """A symlink whose target is a secret file must not launder a read of it."""
    (repo / ".env").write_text("SECRET=1")
    (repo / "notes.txt").symlink_to(repo / ".env")
    decision = check_pre_read(edit_input("notes.txt", tool="Read"), repo)
    assert decision.block
    assert ".env" in decision.message


def test_input_without_file_path_is_allowed(repo: Path, edit_input) -> None:
    assert not check_pre_read(edit_input("", tool="Read"), repo).block


def test_ordinary_file_is_allowed(repo: Path, edit_input) -> None:
    assert not check_pre_read(edit_input("services/x/src/x/a.py", tool="Read"), repo).block


def _tool(repo: Path, tool: str, **tool_input: str) -> HookInput:
    raw = json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": str(repo)})
    parsed = HookInput.parse(raw, default_cwd=repo)
    assert parsed is not None
    return parsed


@pytest.mark.parametrize(
    ("tool", "tool_input"),
    [
        ("Grep", {"pattern": "KEY", "path": ".env"}),
        ("Grep", {"pattern": "KEY", "path": "services/x/.env.local"}),
        ("Grep", {"pattern": "KEY", "glob": ".env*"}),
        ("Grep", {"pattern": "KEY", "path": "services", "glob": "**/.ENV.production"}),
        ("Glob", {"pattern": "**/.env*"}),
        ("Glob", {"pattern": ".env"}),
        ("Glob", {"pattern": ".env.local", "path": "services/x"}),
        ("Glob", {"pattern": "*.env"}),
        ("Glob", {"pattern": "?env"}),
        ("Glob", {"pattern": ".env.*"}),
        ("Glob", {"pattern": "*.local"}),
        ("Glob", {"pattern": "*.production"}),
        ("Glob", {"pattern": "src/*.local"}),
        ("Glob", {"pattern": "*env*"}),
        ("Glob", {"pattern": "{.env,a}"}),
        ("Grep", {"pattern": "K", "glob": "*.env"}),
        ("Grep", {"pattern": "K", "glob": "services/**/{a,.env.local}"}),
        ("Grep", {"pattern": "K", "glob": "*.ENV"}),
    ],
)
def test_grep_and_glob_targeting_secrets_are_blocked(
    repo: Path, tool: str, tool_input: dict[str, str]
) -> None:
    decision = check_pre_read(_tool(repo, tool, **tool_input), repo)
    assert decision.block
    assert ".env.example" in decision.message


@pytest.mark.parametrize(
    ("tool", "tool_input"),
    [
        ("Grep", {"pattern": ".env", "path": "docs"}),  # searching FOR the text ".env" is fine
        ("Grep", {"pattern": "KEY", "glob": "*.py"}),
        ("Glob", {"pattern": "**/*.py"}),
        ("Glob", {"pattern": "**/.env.example"}),
        ("Glob", {"pattern": "**/*"}),
        ("Glob", {"pattern": "*"}),
        ("Glob", {"pattern": "**"}),
        ("Glob", {"pattern": "*.*"}),
        ("Glob", {"pattern": "src/**/*"}),
        ("Glob", {"pattern": "src/**"}),
        ("Glob", {"pattern": "docs/*"}),
        ("Glob", {"pattern": "*/*"}),
        ("Grep", {"pattern": "K", "glob": "services/**/*"}),
        ("Glob", {"pattern": "*.py"}),
        ("Glob", {"pattern": "{a,b}.py"}),
        ("Grep", {"pattern": "K", "glob": "*.{py,toml}"}),
    ],
)
def test_ordinary_grep_and_glob_are_allowed(
    repo: Path, tool: str, tool_input: dict[str, str]
) -> None:
    assert not check_pre_read(_tool(repo, tool, **tool_input), repo).block


def test_secret_in_nested_worktree_is_blocked(repo: Path, edit_input) -> None:
    worktree = repo / ".claude" / "worktrees" / "w1"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: /elsewhere\n")
    decision = check_pre_read(edit_input(str(worktree / ".env"), tool="Read"), repo)
    assert decision.block
