"""Which workspace members does a change touch? Drives CI matrices and `make test-affected`."""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from sb_graph.graph import Graph

# A change to any of these can alter every member's build or tests.
GLOBAL_PATTERNS = (
    "pyproject.toml",
    "ruff.toml",
    "pyrightconfig.json",
    "uv.lock",
    "tach.toml",
    "conftest.py",
    "Makefile",
    "mise.toml",
    "mk/**",
    ".github/**",
    # Schema-only PRs must still run every member's tests (Plan 4 consumers/producers).
    "contracts/**",
)

# Paths that are also tested by a member that does not depend on them: a change to them selects
# that member. The Copier templates render into services/ and are proved by sb-checks'
# test_templates.py, which also compares the template with services/ledger (drift guard) and
# runs the rendered service against libs/py, so changes there select sb-checks too.
TESTED_BY = (
    ("tools/templates/**", "sb-checks"),
    ("services/ledger/**", "sb-checks"),
    ("libs/py/**", "sb-checks"),
)


class GitError(RuntimeError):
    """A git command failed (usually: the base ref does not exist locally)."""


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
        )
    except subprocess.CalledProcessError as exc:
        raise GitError(
            f"`git {' '.join(args)}` failed: {exc.stderr.strip()}. If the base ref is missing, "
            "run `git fetch origin main` or pass --base <ref>."
        ) from exc
    return result.stdout


def changed_files(
    root: Path, base: str, *, include_worktree: bool = True
) -> tuple[PurePosixPath, ...]:
    # --no-renames: a move reports both old and new path, so both owners are affected.
    # -z: NUL-separated and never quoted, so non-ASCII paths come through verbatim.
    diff = ("diff", "--name-only", "--no-renames", "-z")
    output = _git(root, *diff, f"{base}...HEAD")
    if include_worktree:
        output += _git(root, *diff, "HEAD")
        output += _git(root, "ls-files", "-z", "--others", "--exclude-standard")
    return tuple(sorted({PurePosixPath(name) for name in output.split("\0") if name}))


def affected_members(graph: Graph, changed: Iterable[PurePosixPath]) -> tuple[str, ...]:
    paths = list(changed)
    if any(path.full_match(pattern) for path in paths for pattern in GLOBAL_PATTERNS):
        return tuple(m.name for m in graph.members)
    direct = {owner.name for path in paths if (owner := graph.owner_of(path)) is not None}
    members = {m.name for m in graph.members}
    direct.update(
        member
        for path in paths
        for pattern, member in TESTED_BY
        if member in members and path.full_match(pattern)
    )
    result = set(direct)
    for name in direct:
        result.update(graph.dependents_closure(name))
    return tuple(sorted(result))
