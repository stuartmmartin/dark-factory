"""`sb-checks doc-commands`: extract the executable blocks of a doc and optionally run them.

A block is executable when its fence info string is exactly ``sh env-setup``. Plain ``sh``
blocks (informational commands, such as installing Docker) are never run.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

__all__ = [
    "BLOCK_TIMEOUT_SECONDS",
    "DEFAULT_TAG",
    "BlockTimeoutError",
    "DocError",
    "extract",
    "run",
]

DEFAULT_TAG = "env-setup"
BLOCK_TIMEOUT_SECONDS = 900
_FENCE = "```"


class DocError(ValueError):
    """The doc has a fence that would silently drop or truncate an executable block."""


class BlockTimeoutError(RuntimeError):
    """A block ran longer than its timeout."""

    def __init__(self, number: int, timeout: float) -> None:
        super().__init__(f"block {number} timed out after {timeout:g}s")
        self.number = number


def extract(markdown: str, tag: str = DEFAULT_TAG) -> list[str]:
    """Bodies of the fenced blocks whose info string is exactly ``sh <tag>``, in order.

    Raises DocError for an unterminated ``sh <tag>`` block, and for a fence that mentions the
    tag but is not exactly ``sh <tag>`` (``sh env-setup extra``, ``bash env-setup``): those would
    otherwise be skipped without anyone noticing.
    """
    wanted = f"{_FENCE}sh {tag}"
    blocks: list[str] = []
    body: list[str] | None = None
    in_other_fence = False
    start = 0
    for number, line in enumerate(markdown.splitlines(), start=1):
        stripped = line.strip()
        if body is not None:
            if stripped == _FENCE:
                blocks.append("".join(f"{text}\n" for text in body))
                body = None
            else:
                body.append(line)
        elif in_other_fence:
            in_other_fence = stripped != _FENCE
        elif stripped == wanted:
            body = []
            start = number
        elif stripped.startswith(_FENCE):
            if tag in stripped.removeprefix(_FENCE).split():
                raise DocError(
                    f"line {number}: fence {stripped!r} is ignored; use exactly {wanted!r}"
                )
            in_other_fence = True
    if body is not None:
        raise DocError(f"line {start}: unterminated {wanted!r} block")
    return blocks


def run(
    blocks: list[str],
    root: Path,
    announce: Callable[[int, int, str], None] | None = None,
    timeout: float = BLOCK_TIMEOUT_SECONDS,
) -> int | None:
    """Run each block with ``bash -euo pipefail -c`` from ``root``.

    Returns None when every block passes, else the 1-based number of the first failing block
    (later blocks do not run). A block over ``timeout`` seconds raises BlockTimeoutError.
    """
    for number, block in enumerate(blocks, start=1):
        if announce is not None:
            announce(number, len(blocks), block)
        # The command text comes from a committed, reviewed doc; nothing external is executed.
        argv = ["bash", "-euo", "pipefail", "-c", block]
        try:
            result = subprocess.run(argv, cwd=root, check=False, timeout=timeout)  # noqa: S603
        except subprocess.TimeoutExpired as exc:
            raise BlockTimeoutError(number, timeout) from exc
        if result.returncode != 0:
            return number
    return None
