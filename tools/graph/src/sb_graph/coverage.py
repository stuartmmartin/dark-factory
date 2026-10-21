"""Is every member's src/ covered by the root tool configs (pytest, pyright, tach, import-linter)?

A new member that no root config mentions is silently untested, untyped or unpoliced, so
`sb-graph check` reports each gap and names the file to update.
"""

from __future__ import annotations

import configparser
import json
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import cast

from sb_graph.graph import Graph

_IMPORTLINTER_INI = ".importlinter"
_PYRIGHTCONFIG = "pyrightconfig.json"


@dataclass(frozen=True)
class _RootConfig:
    testpaths: tuple[PurePosixPath, ...] | None  # None: unset, pytest collects the whole repo
    pyright_include: tuple[PurePosixPath, ...] | None  # None: unset, pyright checks everything
    pyright_hint: str
    tach_source_roots: frozenset[PurePosixPath]
    root_packages: frozenset[str]
    importlinter_hint: str


def _toml(file: Path) -> dict[str, object]:
    if not file.is_file():
        return {}
    try:
        return tomllib.loads(file.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return {}  # the owning tool reports its own malformed config


def _get(data: dict[str, object], key: str, *rest: str) -> object:
    value = data.get(key)
    if not rest:
        return value
    if isinstance(value, dict):
        return _get(cast(dict[str, object], value), *rest)
    return None


def _str_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v for v in cast(list[object], value) if isinstance(v, str)]
    return []


def _paths(value: object) -> tuple[PurePosixPath, ...] | None:
    if value is None:
        return None
    return tuple(PurePosixPath(entry) for entry in _str_list(value))


def _importlinter_packages(root: Path, pyproject: dict[str, object]) -> tuple[frozenset[str], str]:
    ini = root / _IMPORTLINTER_INI
    if ini.is_file():
        parser = configparser.ConfigParser()
        parser.read(ini, encoding="utf-8")
        raw = " ".join(
            parser.get("importlinter", key, fallback="")
            for key in ("root_packages", "root_package")
        )
        return frozenset(raw.split()), f"{_IMPORTLINTER_INI} [importlinter] root_packages"
    packages = [
        *_str_list(_get(pyproject, "tool", "importlinter", "root_packages")),
        *_str_list(_get(pyproject, "tool", "importlinter", "root_package")),
    ]
    return frozenset(packages), "pyproject.toml [tool.importlinter].root_packages"


def _pyright_include(
    root: Path, pyproject: dict[str, object]
) -> tuple[tuple[PurePosixPath, ...] | None, str]:
    """pyright reads pyrightconfig.json when present and then ignores [tool.pyright]."""
    config = root / _PYRIGHTCONFIG
    if config.is_file():
        try:
            loaded: object = json.loads(config.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded = {}  # pyright reports its own malformed config
        data = cast(dict[str, object], loaded) if isinstance(loaded, dict) else {}
        return _paths(data.get("include")), f"{_PYRIGHTCONFIG} include"
    return _paths(_get(pyproject, "tool", "pyright", "include")), (
        "pyproject.toml [tool.pyright].include"
    )


def _load_root_config(root: Path) -> _RootConfig:
    pyproject = _toml(root / "pyproject.toml")
    packages, hint = _importlinter_packages(root, pyproject)
    pyright_include, pyright_hint = _pyright_include(root, pyproject)
    return _RootConfig(
        testpaths=_paths(_get(pyproject, "tool", "pytest", "ini_options", "testpaths")),
        pyright_include=pyright_include,
        pyright_hint=pyright_hint,
        tach_source_roots=frozenset(
            PurePosixPath(p) for p in _str_list(_get(_toml(root / "tach.toml"), "source_roots"))
        ),
        root_packages=packages,
        importlinter_hint=hint,
    )


def _covered(path: PurePosixPath, entries: Iterable[PurePosixPath] | None) -> bool:
    """True when PATH is (under) an entry; entries may be globs, as pytest and pyright allow."""
    if entries is None:
        return True
    candidates = [path, *path.parents]
    return any(c == e or c.full_match(str(e)) for e in entries for c in candidates)


def coverage_errors(root: Path, graph: Graph) -> list[str]:
    config = _load_root_config(root)
    errors: list[str] = []
    for member in graph.members:
        src = member.path / "src"
        if not (root / src).is_dir():
            continue
        prefix = f"{member.name}: "
        if not _covered(member.path, config.testpaths):
            errors.append(
                f"{prefix}{member.path} is not under pytest testpaths; "
                "add it to pyproject.toml [tool.pytest.ini_options].testpaths"
            )
        if not _covered(src, config.pyright_include):
            errors.append(
                f"{prefix}{src} is not in pyright include; add it to {config.pyright_hint}"
            )
        if src not in config.tach_source_roots:
            errors.append(
                f"{prefix}{src} is not in tach source_roots; add it to tach.toml source_roots"
            )
        if member.import_name not in config.root_packages:
            errors.append(
                f"{prefix}{member.import_name} is not in import-linter root_packages; "
                f"add it to {config.importlinter_hint}"
            )
    return errors
