"""PreToolUse guard for Edit/Write/MultiEdit/NotebookEdit: secrets, guardrails, merged migrations.

Guardrail files encode the architecture's boundaries and the strictness of every check. Agents
that hit a violation must fix the code, not loosen the rule, so those files are human-owned
(`sb_agentkit.guardrails`). A human launches Claude with `SB_ALLOW_GUARDRAIL_EDITS` set (`1`, or
a comma-separated list of paths/globs) to change them deliberately. Secret files have no override.
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Protocol

from sb_agentkit.guardrails import (
    OVERRIDE_ALL,
    OVERRIDE_ENV,
    is_guardrail,
    is_secret,
    is_user_claude_config,
    override_allows,
)
from sb_agentkit.hookio import Decision, HookInput
from sb_agentkit.paths import target_views

MIGRATION_PATTERN = "services/*/migrations/versions/*.py"
OVERRIDE_HINT = (
    f"Override: {OVERRIDE_ENV} (a human sets it when launching Claude; see docs/agents/hooks.md)."
)


class BaseRef(Protocol):
    def exists_on_base(self, rel: PurePosixPath, root: Path) -> bool: ...


class GitBaseRef:
    """Answers "is this file already merged?" against origin/main (falling back to main)."""

    def exists_on_base(self, rel: PurePosixPath, root: Path) -> bool:
        for ref in ("origin/main", "main"):
            result = subprocess.run(  # noqa: S603 - fixed argv, no shell
                ["git", "cat-file", "-e", f"{ref}:{rel}"],  # noqa: S607
                cwd=root,
                capture_output=True,
                check=False,
            )
            if result.returncode == 0:
                return True
        return False


def check_pre_edit(
    inp: HookInput,
    root: Path,
    base: BaseRef,
    env: Mapping[str, str],
    home: Path | None = None,
) -> Decision:
    target = inp.target()
    if not target:
        return Decision.allow()
    absolute = Path(target) if Path(target).is_absolute() else root / target
    if (
        is_user_claude_config(absolute, home or Path.home())
        and env.get(OVERRIDE_ENV) != OVERRIDE_ALL
    ):
        return Decision.deny(
            f"{target} is under ~/.claude: user-level Claude settings can switch off this repo's "
            f"hooks, so agents never write there. {OVERRIDE_HINT}"
        )
    views = target_views(target, root)
    for _, rel in views:
        if is_secret(rel):
            return Decision.deny(
                f"{rel} holds live secrets and must never be edited by an agent. "
                "Put shareable keys (no values) in .env.example instead (C14)."
            )
    for _, rel in views:
        if is_guardrail(rel) and not override_allows(rel, env):
            return Decision.deny(
                f"{rel} is a human-owned guardrail (boundaries, strictness, hooks, CI). Do not "
                "loosen it to make a check pass: fix the code. If the rule itself is wrong, stop "
                f"and propose the exact change in your summary for a human to apply (A15). "
                f"{OVERRIDE_HINT}"
            )
    for view_root, rel in views:
        if rel.full_match(MIGRATION_PATTERN, case_sensitive=False) and base.exists_on_base(
            rel, view_root
        ):
            return Decision.deny(
                f"{rel} is already merged; merged migrations are immutable. Create a new "
                'revision with `make db-revision SVC=<svc> M="..."` instead.'
            )
    return Decision.allow()
