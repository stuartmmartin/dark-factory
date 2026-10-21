"""Lint and type strictness live only in the root ruff.toml / pyrightconfig.json.

A workspace member's own pyproject.toml must not carry a [tool.ruff], [tool.pyright] or
[tool.mypy] table: it would loosen (or shadow) the root config for that member. sb_checks stays
independent of sb_graph, so instead of `sb_graph.workspace.discover_members` this globs the member
pyproject.toml files directly (libs/py/*, services/*, tools/*). The root pyproject.toml never
matches these globs. This is a repo-level check (`scan`), not a per-Python-file one.

Documented blind spot: a member-level `ruff.toml` / `.ruff.toml` file (instead of a table in
pyproject.toml) is not detected; see ``TestDocumentedBlindSpots``.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import cast

from sb_checks.core import Violation

_MEMBER_GLOBS = (
    "libs/py/*/pyproject.toml",
    "services/*/pyproject.toml",
    "tools/*/pyproject.toml",
)
_BANNED_TABLES = ("ruff", "pyright", "mypy")


class NoMemberToolConfigCheck:
    check_id = "no-member-tool-config"
    description = "tool config lives only in root ruff.toml / pyrightconfig.json"

    def scan(self, root: Path) -> Iterator[Violation]:
        for pattern in _MEMBER_GLOBS:
            for file in sorted(root.glob(pattern)):
                rel = PurePosixPath(file.relative_to(root).as_posix())
                yield from self._file_violations(rel, file.read_text(encoding="utf-8"))

    def _file_violations(self, rel: PurePosixPath, text: str) -> Iterator[Violation]:
        try:
            data = cast(dict[str, object], tomllib.loads(text))
        except tomllib.TOMLDecodeError:
            return  # not this check's job; pip/uv fail on it anyway
        tool = data.get("tool")
        if not isinstance(tool, dict):
            return
        tables = cast(dict[str, object], tool)
        for name in _BANNED_TABLES:
            if name in tables:
                message = f"[tool.{name}] in a member pyproject.toml: {self.description}"
                yield Violation(rel, _line_of(text, name), self.check_id, message)


def _line_of(text: str, name: str) -> int:
    needle = f"[tool.{name}"
    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip().startswith(needle):
            return number
    return 1
