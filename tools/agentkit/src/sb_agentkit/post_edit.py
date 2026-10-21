"""PostToolUse hook for edits: ruff fix + format + pyright on the edited Python file only.

Per-file and fast (target < 3s). Remaining lint or type errors go back to the agent (exit 2)
so it fixes them in the same turn instead of discovering them in CI.

It must not fight TDD: `ruff --fix` never deletes unused imports (F401) or commented-out code
(ERA001), because a test written first imports what doesn't exist yet. For the same reason,
pyright errors in a file under `tests/` are reported as information (exit 0); in `src` they block.
"""

from __future__ import annotations

from pathlib import Path

from sb_agentkit.hookio import Decision, HookInput
from sb_agentkit.paths import repo_relative, repo_root_for
from sb_agentkit.runner import Runner, tail, tool_argv

MAX_FEEDBACK_LINES = 80
UNFIXABLE = "F401,ERA001"
RUFF_CONFIG = "ruff.toml"


def check_post_edit(inp: HookInput, root: Path, run: Runner) -> Decision:
    target = inp.target()
    if not target:
        return Decision.allow()
    absolute = Path(target) if Path(target).is_absolute() else root / target
    root = repo_root_for(absolute, root)
    rel = repo_relative(str(absolute), root)
    if rel is None or rel.suffix != ".py" or not (root / rel).is_file():
        return Decision.allow()
    path = str(rel)
    ruff, pyright = tool_argv(root, "ruff"), tool_argv(root, "pyright")
    config = ["--config", RUFF_CONFIG]  # explicit: a member pyproject.toml must not shadow it
    lint = run([*ruff, "check", *config, "--fix", "--unfixable", UNFIXABLE, path], root)
    run([*ruff, "format", *config, path], root)
    types = run([*pyright, path], root)
    blocking = [lint.output] if lint.returncode != 0 else []
    if types.returncode != 0 and "tests" not in rel.parts:
        blocking.append(types.output)
    if blocking:
        return Decision.deny(
            f"{path} still has lint/type errors after auto-fix. Fix them now:\n"
            + tail("\n".join(blocking), MAX_FEEDBACK_LINES)
        )
    if types.returncode != 0:
        return Decision.inform(
            f"{path}: pyright errors (informational in tests/, e.g. a test-first import of "
            "code you haven't written yet; they must be gone by `make check`):\n"
            + tail(types.output, MAX_FEEDBACK_LINES)
        )
    return Decision.allow()
