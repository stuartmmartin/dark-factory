"""Pick which AI reviewers a PR needs from its changed paths (claude-review.yml matrix).

A change to a guardrail file (`sb_agentkit.guardrails`, the same list the hooks enforce) gets
both blocking reviewers, so a PR that only loosens a check is never waved through unreviewed.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath

from sb_agentkit.guardrails import is_guardrail

__all__ = ["Reviewer", "matrix_json", "reviewers_for"]

CODE_PATTERNS = ("libs/**/*.py", "services/**/*.py", "tools/**/*.py", "**/pyproject.toml")
BOUNDARY_PATTERNS = (".importlinter", "tach.toml", "tools/checks/allowlist.toml")
SECURITY_PATTERNS = (
    # At this scale every runtime service change can affect authorization or trusted context.
    "services/*/src/**",
    "services/*/migrations/**",
    "libs/py/sb_http/**",
    "libs/py/sb_db/**",
    "libs/py/sb_admin/**",
    "libs/py/sb_messaging/**",
    "libs/py/sb_workflows/**",
    "libs/py/sb_kernel/**",
    "libs/py/sb_obs/**",
    "contracts/**",
    ".github/workflows/**",
    "**/Dockerfile",
    "deploy/**",
    "uv.lock",
    "**/pyproject.toml",
    "compose/**",
)
ORDER = ("security", "architecture", "engineering")
# Every requested reviewer must produce valid evidence. Advisory findings can still PASS;
# blocking engineering findings (e.g. missing tests) must never be waived by the focus.
BLOCKING = frozenset(ORDER)


@dataclass(frozen=True)
class Reviewer:
    name: str
    blocking: bool


def _any(paths: list[PurePosixPath], patterns: tuple[str, ...]) -> bool:
    return any(path.full_match(pattern) for path in paths for pattern in patterns)


def reviewers_for(paths: Iterable[PurePosixPath]) -> list[Reviewer]:
    changed = list(paths)
    names: set[str] = set()
    if _any(changed, SECURITY_PATTERNS):
        names.update({"security", "engineering"})
    if _any(changed, CODE_PATTERNS) or _any(changed, BOUNDARY_PATTERNS):
        names.update({"architecture", "engineering"})
    if any(is_guardrail(path) for path in changed):
        names.update({"security", "architecture"})
    return [Reviewer(name, name in BLOCKING) for name in ORDER if name in names]


def matrix_json(reviewers: Iterable[Reviewer]) -> str:
    return json.dumps(
        {"include": [{"reviewer": r.name, "blocking": r.blocking} for r in reviewers]}
    )
