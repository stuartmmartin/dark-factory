"""Find which workspace members a member's src/ actually imports."""

from __future__ import annotations

import ast
from collections.abc import Sequence
from pathlib import Path

from sb_graph.workspace import Member, WorkspaceError


def parse_file(root: Path, file: Path) -> ast.Module:
    """Parse FILE; a syntax error becomes a WorkspaceError naming repo-relative file:line."""
    rel = file.relative_to(root).as_posix()
    try:
        return ast.parse(file.read_text(encoding="utf-8"), filename=rel)
    except SyntaxError as exc:
        raise WorkspaceError(f"{rel}:{exc.lineno}: syntax error: {exc.msg}") from exc


def imported_roots(tree: ast.Module) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def actual_internal_deps(root: Path, member: Member, members: Sequence[Member]) -> tuple[str, ...]:
    by_import = {m.import_name: m.name for m in members}
    found: set[str] = set()
    src = root / member.path / "src"
    for file in sorted(src.rglob("*.py")):
        for imported in imported_roots(parse_file(root, file)):
            owner = by_import.get(imported)
            if owner is not None and owner != member.name:
                found.add(owner)
    return tuple(sorted(found))
