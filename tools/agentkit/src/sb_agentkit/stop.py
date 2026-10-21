"""Completion feedback over the session's committed, working-tree and untracked changes.

Run check-fast against the same baseline as the guardrail check, including configuration and
docs changes, unless the working state is exactly the one the last passing check-fast saw this
session (a marker beside the session baseline): Stop fires at the end of every turn, and
re-checking an unchanged tree only burns time and tokens. `SB_STOP_CHECK=0`, set by a human when
launching Claude, skips check-fast for the session; the guardrail check always runs.

Git inspection errors fail closed. A repeated failed Stop permits escalation with an explicit
BLOCKED message, never silently claims verification succeeded. CI remains the merge boundary;
local hooks are feedback, not a security sandbox or an atomic snapshot of a live tree.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path

from sb_agentkit.guardrail_diff import GitError, changed_paths, comparison_base
from sb_agentkit.guardrails import OVERRIDE_ENV, is_guardrail, override_allows
from sb_agentkit.hookio import Decision, HookInput
from sb_agentkit.paths import repo_root_for
from sb_agentkit.runner import Runner, tail
from sb_agentkit.session_base import session_base_path

MAX_FEEDBACK_LINES = 60
STOP_CHECK_ENV = "SB_STOP_CHECK"
GIT_TIMEOUT_SECONDS = 60


def _git(root: Path, *args: str, env: Mapping[str, str] | None = None) -> str:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", *args],  # noqa: S607
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=GIT_TIMEOUT_SECONDS,
    ).stdout.strip()


def working_state(root: Path) -> str | None:
    """HEAD plus a tree of every non-ignored file as it is now, written through a scratch copy
    of the index (the real index is untouched). Equal values mean nothing changed; None if git
    fails."""
    try:
        head = _git(root, "rev-parse", "HEAD")
        index = Path(_git(root, "rev-parse", "--path-format=absolute", "--git-path", "index"))
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp) / "index"
            if index.is_file():
                shutil.copyfile(index, scratch)
            env = {**os.environ, "GIT_INDEX_FILE": str(scratch)}
            _git(root, "add", "-A", env=env)
            tree = _git(root, "write-tree", env=env)
    except (subprocess.SubprocessError, OSError):
        return None
    return f"{head} {tree}\n"


def _passed_marker(root: Path, session_id: str, run: Runner) -> Path | None:
    base = session_base_path(root, session_id, run)
    return None if base is None else base.with_name(f"stop-passed-{session_id}")


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _failure(inp: HookInput, message: str) -> Decision:
    if inp.stop_hook_active:
        return Decision.inform(
            "BLOCKED: completion verification has not passed. Automatic repair has stopped. "
            "Human review is required; this task is not verified.\n" + message
        )
    return Decision.deny(
        "BLOCKED: completion verification failed. Repair or report these blockers to the human.\n"
        + message
    )


def _check_fast(
    inp: HookInput, root: Path, base: str, run: Runner, state: Callable[[Path], str | None]
) -> str | None:
    """Run check-fast unless this exact state already passed; the failure message, if any."""
    marker = _passed_marker(root, inp.session_id, run)
    current = state(root) if marker is not None else None
    if marker is not None and current is not None and _read(marker) == current:
        return None
    result = run(["make", "check-fast", f"BASE={base}"], root)
    if result.returncode != 0:
        return (
            "`make check-fast` fails on the current inputs. Fix these before finishing, "
            "or report a pre-existing/out-of-scope failure as BLOCKED:\n"
            + tail(result.output, MAX_FEEDBACK_LINES)
        )
    if marker is not None and current is not None:
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(current, encoding="utf-8")
        except OSError:
            pass  # no marker only means the next Stop checks again
    return None


def check_stop(
    inp: HookInput,
    root: Path,
    run: Runner,
    env: Mapping[str, str],
    state: Callable[[Path], str | None] = working_state,
) -> Decision:
    root = repo_root_for(inp.cwd, root)
    try:
        base = comparison_base(root, run=run, session_id=inp.session_id)
        paths = changed_paths(root, base, run)
    except GitError as exc:
        return _failure(inp, f"Could not inspect completion inputs: {exc}")
    problems: list[str] = []
    guarded = [p for p in paths if is_guardrail(p) and not override_allows(p, env)]
    if guarded:
        listing = "\n".join(f"  - {path}" for path in guarded)
        problems.append(
            f"These guardrail files differ from the session/branch baseline:\n{listing}\n"
            "Some uncommitted changes may predate this session: never revert another person's "
            "work. Request human review/authorization; only a human sets "
            f"{OVERRIDE_ENV}. See docs/agents/hooks.md."
        )
    if paths and env.get(STOP_CHECK_ENV) != "0":
        failure = _check_fast(inp, root, base, run, state)
        if failure:
            problems.append(failure)
    return _failure(inp, "\n\n".join(problems)) if problems else Decision.allow()
