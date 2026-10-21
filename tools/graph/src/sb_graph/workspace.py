"""Discover uv workspace members and the internal dependencies they declare."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import cast

KIND_BY_TOP_DIR = {"libs": "lib", "services": "service", "tools": "tool", "apps": "app"}
_REQUIREMENT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")


class WorkspaceError(ValueError):
    """The workspace or a member's pyproject.toml is malformed."""


@dataclass(frozen=True, order=True)
class Member:
    name: str
    import_name: str
    path: PurePosixPath
    kind: str
    language: str
    declared: tuple[str, ...]
    # Workspace members named in any [dependency-groups] group: test/dev-only edges.
    test_declared: tuple[str, ...] = ()


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _load(file: Path, root: Path) -> dict[str, object]:
    rel = file.relative_to(root).as_posix()
    try:
        text = file.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise WorkspaceError(f"{rel}: not found; run from the repo root or pass --root") from exc
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise WorkspaceError(f"{rel}: invalid TOML: {exc}") from exc


def _sub_table(data: dict[str, object], key: str) -> dict[str, object]:
    value = data.get(key, {})
    if isinstance(value, dict):
        return cast(dict[str, object], value)
    return {}


def _table(data: dict[str, object], *keys: str) -> dict[str, object]:
    current = data
    for key in keys:
        current = _sub_table(current, key)
    return current


def _strings(value: object, where: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(
        isinstance(v, str) for v in cast(list[object], value)
    ):
        raise WorkspaceError(f"{where} must be a list of strings")
    return cast(list[str], value)


def _requirement_name(requirement: str, where: str) -> str:
    match = _REQUIREMENT_NAME.match(requirement.strip())
    if match is None:
        raise WorkspaceError(f"{where}: cannot parse requirement {requirement!r}")
    return normalize(match.group(0))


def _group_requirements(config: dict[str, object], where: str) -> list[str]:
    """Requirement names from every [dependency-groups] group ({include-group} tables skipped)."""
    names: list[str] = []
    for group, value in _sub_table(config, "dependency-groups").items():
        if not isinstance(value, list):
            raise WorkspaceError(f"{where}: [dependency-groups].{group} must be a list")
        names.extend(
            _requirement_name(item, where)
            for item in cast(list[object], value)
            if isinstance(item, str)
        )
    return names


def _member_directories(root: Path, workspace: dict[str, object]) -> list[Path]:
    """Directories matched by `members` globs, minus `exclude` globs (uv semantics)."""
    where = "pyproject.toml [tool.uv.workspace]"
    globs = _strings(workspace.get("members"), f"{where}.members")
    excluded = {
        d for g in _strings(workspace.get("exclude"), f"{where}.exclude") for d in root.glob(g)
    }
    return sorted(
        {
            d
            for g in globs
            for d in root.glob(g)
            if d not in excluded and (d / "pyproject.toml").is_file()
        }
    )


def discover_members(root: Path) -> tuple[Member, ...]:
    root_config = _load(root / "pyproject.toml", root)
    directories = _member_directories(root, _table(root_config, "tool", "uv", "workspace"))
    parsed: list[tuple[str, str, PurePosixPath, str, list[str], list[str]]] = []
    for directory in directories:
        rel = PurePosixPath(directory.relative_to(root).as_posix())
        where = f"{rel}/pyproject.toml"
        config = _load(directory / "pyproject.toml", root)
        project = _table(config, "project")
        raw_name = project.get("name")
        if not isinstance(raw_name, str) or not raw_name:
            raise WorkspaceError(f"{where}: [project].name is required")
        name = normalize(raw_name)
        deps = [_requirement_name(r, where) for r in _strings(project.get("dependencies"), where)]
        test_deps = _group_requirements(config, where)
        override = _table(config, "tool", "sb").get("import-name")
        import_name = override if isinstance(override, str) else name.replace("-", "_")
        kind = KIND_BY_TOP_DIR.get(rel.parts[0])
        if kind is None:
            raise WorkspaceError(f"{rel}: members must live under one of {sorted(KIND_BY_TOP_DIR)}")
        parsed.append((name, import_name, rel, kind, deps, test_deps))
    names = {entry[0] for entry in parsed}
    return tuple(
        sorted(
            Member(
                name,
                import_name,
                rel,
                kind,
                "python",
                tuple(sorted(set(deps) & names)),
                tuple(sorted((set(test_deps) & names) - {name})),
            )
            for name, import_name, rel, kind, deps, test_deps in parsed
        )
    )
