"""Structural invariants of .claude/settings.json: which hooks run, and on what."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import cast

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SETTINGS = REPO_ROOT / ".claude" / "settings.json"
HOOK_SH = REPO_ROOT / "tools" / "agentkit" / "hook.sh"

Mapping = dict[str, object]


@pytest.fixture(scope="module")
def settings() -> Mapping:
    return cast(Mapping, json.loads(SETTINGS.read_text(encoding="utf-8")))


def _hooks(settings: Mapping) -> dict[str, list[Mapping]]:
    return cast(dict[str, list[Mapping]], settings["hooks"])


def _commands(entry: Mapping) -> list[str]:
    return [str(h["command"]) for h in cast(list[Mapping], entry["hooks"])]


def test_no_subagent_stop_hook(settings: Mapping) -> None:
    """The parent's Stop hook covers subagent work; running check-fast per subagent is waste."""
    assert "SubagentStop" not in _hooks(settings)


def test_session_start_warns_when_hooks_are_inactive(settings: Mapping) -> None:
    entries = _hooks(settings)["SessionStart"]
    commands = [c for entry in entries for c in _commands(entry)]
    assert commands == ['"$CLAUDE_PROJECT_DIR"/tools/agentkit/hook.sh --check']


def test_pre_read_guards_read_grep_and_glob(settings: Mapping) -> None:
    matchers = {
        str(entry.get("matcher")): _commands(entry) for entry in _hooks(settings)["PreToolUse"]
    }
    assert any("hook.sh pre-read" in c for c in matchers["Read|Grep|Glob"])


def test_every_hook_runs_through_the_launcher(settings: Mapping) -> None:
    """hook.sh finds sb-agentkit in this checkout's .venv or the main checkout's, so a new
    worktree is guarded without its own `make bootstrap`."""
    for entries in _hooks(settings).values():
        for command in (c for entry in entries for c in _commands(entry)):
            assert command.startswith('"$CLAUDE_PROJECT_DIR"/tools/agentkit/hook.sh '), command


def test_force_push_is_denied_but_push_to_main_is_not(settings: Mapping) -> None:
    deny = cast(list[str], cast(Mapping, settings["permissions"])["deny"])
    assert "Bash(git push --force*)" in deny
    assert "Bash(git push -f*)" in deny
    assert not [rule for rule in deny if "main" in rule]


def _fake_agentkit(venv_root: Path) -> None:
    bin_dir = venv_root / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    script = bin_dir / "sb-agentkit"
    script.write_text(f'#!/bin/sh\necho "{venv_root.name} $*"\n')
    script.chmod(0o755)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _hook(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(HOOK_SH), *args],
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(project)},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def main_with_worktree(tmp_path: Path) -> tuple[Path, Path]:
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    _git(main, "-c", "user.name=T", "-c", "user.email=t@x", "commit", "-qm", "i", "--allow-empty")
    worktree = main / ".claude" / "worktrees" / "w1"
    _git(main, "worktree", "add", "-q", str(worktree), "-b", "w1")
    return main, worktree


def test_launcher_uses_the_main_checkouts_venv_in_a_bare_worktree(main_with_worktree) -> None:
    main, worktree = main_with_worktree
    _fake_agentkit(main)
    result = _hook(worktree, "pre-bash")
    assert result.stdout == "main hook pre-bash\n"
    assert _hook(worktree, "--check").stdout == ""


def test_launcher_prefers_the_worktrees_own_venv(main_with_worktree) -> None:
    main, worktree = main_with_worktree
    _fake_agentkit(main)
    _fake_agentkit(worktree)
    assert _hook(worktree, "stop").stdout == "w1 hook stop\n"


def test_launcher_check_warns_when_no_venv_exists(main_with_worktree) -> None:
    _, worktree = main_with_worktree
    result = _hook(worktree, "--check")
    assert result.returncode == 0
    assert "INACTIVE" in result.stdout
    assert _hook(worktree, "pre-edit").returncode != 0
