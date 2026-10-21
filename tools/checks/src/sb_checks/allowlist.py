"""Justified exemptions from convention checks. Entries that excuse nothing are violations.

The allowlist is human-owned (CODEOWNERS + agent hook). Every entry needs a reason, and an
entry whose file was fixed or deleted fails the run, so exemptions cannot outlive the debt.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import cast

from sb_checks.core import Violation

ALLOWLIST_PATH = PurePosixPath("tools/checks/allowlist.toml")
MIN_REASON_LENGTH = 10


@dataclass(frozen=True)
class AllowEntry:
    check_id: str
    path: PurePosixPath
    reason: str


class AllowlistError(ValueError):
    """The allowlist file is malformed or an entry lacks a justification."""


def load_allowlist(file: Path) -> tuple[AllowEntry, ...]:
    if not file.exists():
        return ()
    try:
        data = tomllib.loads(file.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise AllowlistError(f"{file}: invalid TOML: {exc}") from exc
    raw: object = data.get("allow", [])
    if not isinstance(raw, list):
        raise AllowlistError(f"{file}: 'allow' must be an array of tables")
    entries: list[AllowEntry] = []
    for index, item in enumerate(cast(list[object], raw)):
        entries.append(_parse_entry(file, index, item))
    return tuple(entries)


def _parse_entry(file: Path, index: int, item: object) -> AllowEntry:
    if not isinstance(item, dict):
        raise AllowlistError(f"{file}: allow[{index}] must be a table")
    table = cast(dict[str, object], item)
    check_id, path, reason = table.get("check"), table.get("path"), table.get("reason", "")
    if not isinstance(check_id, str) or not isinstance(path, str):
        raise AllowlistError(f"{file}: allow[{index}] needs string 'check' and 'path'")
    if not isinstance(reason, str) or len(reason.strip()) < MIN_REASON_LENGTH:
        raise AllowlistError(
            f"{file}: allow[{index}] ({path}) needs a 'reason' explaining the exemption"
        )
    return AllowEntry(check_id, PurePosixPath(path), reason.strip())


def apply_allowlist(
    violations: Iterable[Violation], entries: Sequence[AllowEntry]
) -> list[Violation]:
    used: set[AllowEntry] = set()
    remaining: list[Violation] = []
    for violation in violations:
        entry = next(
            (e for e in entries if e.check_id == violation.check_id and e.path == violation.path),
            None,
        )
        if entry is None:
            remaining.append(violation)
        else:
            used.add(entry)
    seen: set[tuple[str, PurePosixPath]] = set()
    for entry in entries:
        key = (entry.check_id, entry.path)
        if key in seen:
            remaining.append(
                Violation(
                    ALLOWLIST_PATH,
                    1,
                    "stale-allowlist",
                    f"duplicate allowlist entry for {entry.path} [{entry.check_id}]; delete it",
                )
            )
        elif entry not in used:
            remaining.append(
                Violation(
                    ALLOWLIST_PATH,
                    1,
                    "stale-allowlist",
                    f"entry for {entry.path} [{entry.check_id}] excuses nothing; delete it",
                )
            )
        seen.add(key)
    return sorted(remaining)
