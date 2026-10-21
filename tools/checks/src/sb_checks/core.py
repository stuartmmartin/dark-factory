"""Core types shared by every convention check: violations, file context, the Check protocol."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol, runtime_checkable

SCAN_ROOTS = ("libs", "services", "tools")
# Directory names never scanned. `fixtures` is excluded so checks' own test data does not
# trip them; this is a documented blind spot (real code must never live in `fixtures/`).
EXCLUDED_DIR_NAMES = frozenset(
    {".venv", ".git", "__pycache__", "node_modules", ".mutmut-cache", "fixtures", "build", "dist"}
)


@dataclass(frozen=True, order=True)
class Violation:
    path: PurePosixPath
    line: int
    check_id: str
    message: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: [{self.check_id}] {self.message}"


@dataclass(frozen=True)
class FileContext:
    root: Path
    path: PurePosixPath
    source: str
    tree: ast.Module

    def violation(self, check_id: str, node_or_line: ast.AST | int, message: str) -> Violation:
        line = node_or_line if isinstance(node_or_line, int) else getattr(node_or_line, "lineno", 1)
        return Violation(self.path, int(line), check_id, message)


class Check(Protocol):
    check_id: str
    description: str

    def applies_to(self, path: PurePosixPath) -> bool: ...

    def run(self, ctx: FileContext) -> Iterable[Violation]: ...


@runtime_checkable
class RepoCheck(Protocol):
    """A check over non-Python repo files (e.g. member pyproject.toml), run once per repo."""

    check_id: str
    description: str

    def scan(self, root: Path) -> Iterable[Violation]: ...


AnyCheck = Check | RepoCheck


def matches_any(path: PurePosixPath, patterns: Iterable[str]) -> bool:
    return any(path.full_match(pattern) for pattern in patterns)


def iter_python_files(root: Path) -> Iterator[PurePosixPath]:
    for scan_root in SCAN_ROOTS:
        base = root / scan_root
        if not base.is_dir():
            continue
        for file in sorted(base.rglob("*.py")):
            rel = file.relative_to(root)
            if EXCLUDED_DIR_NAMES.intersection(rel.parts[:-1]):
                continue
            yield PurePosixPath(rel.as_posix())
