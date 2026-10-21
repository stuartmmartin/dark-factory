"""`sb-agentkit guardrail-diff`: guardrail files this branch changed, by any means.

The pre-edit hook only sees Edit/Write tools; a `sed -i` or `cp` through Bash goes around it.
So the Stop hook re-checks the result: every path changed since the session baseline recorded by
the session's first hook call (else against the merge-base with main), whether committed, staged,
unstaged or untracked, that is a guardrail (`sb_agentkit.guardrails`) and is not covered by
`SB_ALLOW_GUARDRAIL_EDITS`. Guardrail changes a human committed before the session are not
flagged. Deliberately not a pre-commit hook: humans commit guardrail changes legitimately.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from sb_agentkit.guardrails import is_guardrail, override_allows
from sb_agentkit.runner import Runner, subprocess_runner
from sb_agentkit.session_base import read_session_base

__all__ = ["GitError", "changed_guardrails", "changed_paths", "comparison_base", "default_base"]


class GitError(RuntimeError):
    """A git command failed (usually: not a git repository)."""


def default_base(root: Path, run: Runner = subprocess_runner) -> str:
    """origin/main when it exists, else main (the Makefile's BASE)."""
    probe = run(["git", "rev-parse", "--verify", "--quiet", "origin/main"], root)
    return "origin/main" if probe.returncode == 0 else "main"


def _is_commit(root: Path, sha: str, run: Runner) -> bool:
    return (
        run(["git", "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"], root).returncode == 0
    )


def _names(output: str) -> set[PurePosixPath]:
    return {PurePosixPath(name) for name in output.split("\0") if name.strip()}


def _git(run: Runner, root: Path, *args: str) -> str:
    result = run(["git", *args], root)
    if result.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {result.output.strip()}")
    return result.output


def comparison_base(
    root: Path, base: str | None = None, run: Runner = subprocess_runner, session_id: str = ""
) -> str:
    """Session start commit, else the merge-base; inability to inspect is never a clean result."""
    against = read_session_base(root, session_id, run)
    if against is not None and not _is_commit(root, against, run):
        against = None  # recorded but gone (gc, rewritten history): never treat as "clean"
    if against is None:
        base = base or default_base(root, run)
        against = _git(run, root, "merge-base", "HEAD", base).strip()
    if not against:
        raise GitError("could not determine the comparison commit")
    return against


def changed_paths(root: Path, against: str, run: Runner = subprocess_runner) -> list[PurePosixPath]:
    """Net tracked and untracked changes, including complete paths under new directories."""
    changed = _names(_git(run, root, "diff", "--name-only", "--no-renames", "-z", against))
    changed |= _names(
        _git(run, root, "ls-files", "--others", "--exclude-standard", "--full-name", "-z")
    )
    return sorted(changed)


def changed_guardrails(
    root: Path,
    base: str | None = None,
    env: Mapping[str, str] | None = None,
    run: Runner = subprocess_runner,
    session_id: str = "",
) -> list[PurePosixPath]:
    env = os.environ if env is None else env
    against = comparison_base(root, base, run, session_id)
    return [
        p
        for p in changed_paths(root, against, run)
        if is_guardrail(p) and not override_allows(p, env)
    ]
