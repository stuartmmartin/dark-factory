"""Normalize the file paths agents pass to tools into repo-relative POSIX paths.

Two views matter for guards: the *resolved* view follows symlinks (so a symlinked repo root,
or a symlink standing in for a guarded file, cannot be used to slip past a path-based guard),
and the *lexical* view preserves the path exactly as requested (so a symlink whose own name
matches a guard pattern is still caught even when what it points to would not be). Guards
should check both and block if either matches.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath


def _repo_relative(path: str, root: Path, *, resolve: bool) -> PurePosixPath | None:
    if not path:
        return None
    candidate = Path(path)
    absolute = candidate if candidate.is_absolute() else root / candidate
    normalized = absolute.resolve(strict=False) if resolve else Path(os.path.normpath(absolute))
    # Try the resolved root first (handles a symlinked/aliased root), then the root exactly as
    # given (handles a `normalized` that was never resolved, i.e. the lexical view).
    for candidate_root in (root.resolve(strict=False), Path(os.path.normpath(root))):
        try:
            rel = normalized.relative_to(candidate_root)
        except ValueError:
            continue
        return PurePosixPath(rel.as_posix())
    return None


def repo_relative(path: str, root: Path) -> PurePosixPath | None:
    """Repo-relative POSIX path for `path`, resolving symlinks (including an aliased root)."""
    return _repo_relative(path, root, resolve=True)


def repo_relative_lexical(path: str, root: Path) -> PurePosixPath | None:
    """Repo-relative POSIX path for `path` exactly as requested: symlinks are not followed."""
    return _repo_relative(path, root, resolve=False)


def repo_root_for(path: Path, fallback: Path) -> Path:
    """The repo that owns `path`: the nearest ancestor holding a `.git` marker (a directory, or
    the file a git worktree has), else `fallback` (CLAUDE_PROJECT_DIR).

    Nested worktrees such as `.claude/worktrees/w1` are their own repos: a guard must see
    `.claude/worktrees/w1/tach.toml` as that worktree's `tach.toml`, not an unguarded path.
    """
    absolute = path if path.is_absolute() else fallback / path
    normalized = Path(os.path.normpath(absolute))
    for candidate in (normalized, *normalized.parents):
        if (candidate / ".git").exists():
            return candidate
    return fallback


def target_views(target: str, fallback: Path) -> tuple[tuple[Path, PurePosixPath], ...]:
    """(owning repo root, repo-relative path) for the lexical and the symlink-resolved view.

    A guard blocks if EITHER view matches, so a symlink cannot launder a write to (or read of)
    a protected file, and a symlinked repo root cannot make a real target look external.
    """
    if not target:
        return ()
    candidate = Path(target)
    absolute = candidate if candidate.is_absolute() else fallback / candidate
    lexical = Path(os.path.normpath(absolute))
    resolved = absolute.resolve(strict=False)
    views: list[tuple[Path, PurePosixPath]] = []
    for view, resolve in ((lexical, False), (resolved, True)):
        root = repo_root_for(view, fallback)
        rel = _repo_relative(str(view), root, resolve=resolve)
        if rel is not None and (root, rel) not in views:
            views.append((root, rel))
    return tuple(views)
