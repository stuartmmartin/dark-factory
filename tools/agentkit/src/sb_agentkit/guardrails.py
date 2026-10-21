"""The one list of protected paths, shared by every guard so they cannot drift apart.

Used by the pre-edit and pre-read hooks, CI review triage, and `sb-agentkit guardrail-diff`
(run by the Stop hook). Guardrail files are the ones that could loosen a check: boundaries,
lint and type strictness, hooks, CI, conventions. Daily-work files such as `pyproject.toml`
(dependencies), the `Makefile` and `mk/*.mk` stay editable: CI runs the gates, and CODEOWNERS
review covers changes to the targets. `.github/CODEOWNERS` lists the same set in its
"Human-owned guardrails" section; a parity test keeps the two in step.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath

__all__ = [
    "GUARDRAIL_PATTERNS",
    "OVERRIDE_ALL",
    "OVERRIDE_ENV",
    "SECRET_EXCEPTIONS",
    "SECRET_PATTERNS",
    "is_guardrail",
    "is_secret",
    "is_user_claude_config",
    "matches_pattern",
    "override_allows",
]

SECRET_PATTERNS = (".env", "**/.env", ".env.*", "**/.env.*")
SECRET_EXCEPTIONS = (".env.example", "**/.env.example")
GUARDRAIL_PATTERNS = (
    # Boundaries and allowlists.
    "tach.toml",
    ".importlinter",
    "tools/checks/allowlist.toml",
    "tools/checks/src/**",
    # Lint and type strictness.
    "ruff.toml",
    ".coveragerc",
    "pyrightconfig.json",
    "conftest.py",
    ".pre-commit-config.yaml",
    # Agent hooks, settings and reviewers.
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".claude/skills/code-review/**",
    ".claude/agents/**",
    "tools/agentkit/**",
    "tools/agentkit/src/**",
    # CI, ownership and git hooks.
    ".github/**",
    ".github/CODEOWNERS",
    ".github/workflows/**",
    ".git/hooks/**",
    # The rules themselves.
    "docs/conventions/**",
)
OVERRIDE_ENV = "SB_ALLOW_GUARDRAIL_EDITS"
OVERRIDE_ALL = "1"


def matches_pattern(rel: PurePosixPath, patterns: Iterable[str]) -> bool:
    return any(rel.full_match(pattern, case_sensitive=False) for pattern in patterns)


def is_secret(rel: PurePosixPath) -> bool:
    return matches_pattern(rel, SECRET_PATTERNS) and not matches_pattern(rel, SECRET_EXCEPTIONS)


def is_guardrail(rel: PurePosixPath) -> bool:
    return matches_pattern(rel, GUARDRAIL_PATTERNS)


def override_allows(rel: PurePosixPath, env: Mapping[str, str]) -> bool:
    """`SB_ALLOW_GUARDRAIL_EDITS=1` allows every guardrail; a comma-separated list of
    repo-relative paths or globs (`tach.toml,.github/workflows/**`) allows only those.
    A directory entry allows everything under it."""
    value = env.get(OVERRIDE_ENV, "").strip()
    if value == OVERRIDE_ALL:
        return True
    for raw in value.split(","):
        entry = raw.strip()
        if not entry:
            continue
        pattern = PurePosixPath(entry)
        if rel.full_match(str(pattern), case_sensitive=False) or rel.is_relative_to(pattern):
            return True
    return False


def is_user_claude_config(target: Path, home: Path) -> bool:
    """True if `target` (absolute) is under ~/.claude, lexically or with symlinks resolved.

    User-level Claude settings can disable this repo's hooks, so agents never write there."""
    claude_dirs = {Path(os.path.normpath(home / ".claude")), (home / ".claude").resolve()}
    views = {Path(os.path.normpath(target)), target.resolve(strict=False)}
    return any(view.is_relative_to(d) for view in views for d in claude_dirs)
