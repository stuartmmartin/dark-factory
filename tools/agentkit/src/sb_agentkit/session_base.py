"""Session baseline: the commit HEAD was at when a Claude session first touched the repo.

`ensure_session_base` is called at the top of the pre-edit, pre-bash and pre-read hooks, so the
first tool call of a session records HEAD before anything can change. `guardrail_diff` (and so
the Stop hook) then compares against it: a guardrail change a human committed before the session
is not flagged, only one made during it. One file per session id, under the git directory (found
with `git rev-parse --git-dir`, so a linked worktree gets its own), never in the worktree.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from sb_agentkit.runner import Runner, subprocess_runner

__all__ = ["ensure_session_base", "read_session_base", "session_base_path"]

_SHA = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
_IGNORED = (OSError, subprocess.SubprocessError, ValueError)  # ValueError: UnicodeDecodeError
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _git_dir(root: Path, run: Runner) -> Path | None:
    result = run(["git", "rev-parse", "--git-dir"], root)
    if result.returncode != 0:
        return None
    git_dir = Path(result.output.strip())
    return git_dir if git_dir.is_absolute() else root / git_dir


def session_base_path(root: Path, session_id: str, run: Runner = subprocess_runner) -> Path | None:
    """The baseline file for this session; None without a usable session id or a git repo."""
    if not _SAFE_ID.match(session_id) or session_id in {".", ".."}:
        return None
    git_dir = _git_dir(root, run)
    return None if git_dir is None else git_dir / "sb-agentkit" / f"session-base-{session_id}"


def ensure_session_base(root: Path, session_id: str, run: Runner = subprocess_runner) -> None:
    """Record `git rev-parse HEAD` for this session if not yet recorded. Idempotent and atomic
    (temp file, then `os.replace`, only while absent); never raises, because a hook must not
    fail on a baseline it could not write."""
    try:
        path = session_base_path(root, session_id, run)
        if path is None or path.exists():
            return
        head = run(["git", "rev-parse", "HEAD"], root).output.strip()
        if not _SHA.match(head):
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            temp.write_text(head + "\n", encoding="utf-8")
            if path.exists():
                return
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)
    except _IGNORED:
        return


def read_session_base(root: Path, session_id: str, run: Runner = subprocess_runner) -> str | None:
    """The recorded baseline commit for this session, or None if absent or unreadable. Anything
    that is not a full commit hash is treated as absent (else it could be read as an option)."""
    try:
        path = session_base_path(root, session_id, run)
        if path is None or not path.is_file():
            return None
        text = path.read_text(encoding="utf-8").strip()
    except _IGNORED:
        return None
    return text if _SHA.match(text) else None
