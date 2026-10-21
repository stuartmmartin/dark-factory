"""Run external commands for hooks; injectable so hook logic is testable without subprocesses."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

TIMEOUT_SECONDS = 600


@dataclass(frozen=True)
class Result:
    returncode: int
    output: str


Runner = Callable[[Sequence[str], Path], Result]


def subprocess_runner(argv: Sequence[str], cwd: Path) -> Result:
    completed = subprocess.run(  # noqa: S603 - argv lists built by this package, no shell
        list(argv), cwd=cwd, capture_output=True, text=True, check=False, timeout=TIMEOUT_SECONDS
    )
    return Result(completed.returncode, completed.stdout + completed.stderr)


def tool_argv(root: Path, tool: str) -> list[str]:
    local = root / ".venv" / "bin" / tool
    return [str(local)] if local.exists() else ["uv", "run", tool]


def tail(text: str, lines: int) -> str:
    return "\n".join(text.rstrip("\n").splitlines()[-lines:])
