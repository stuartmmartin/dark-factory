"""Module names must say what the module does; grab-bag names are banned."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import PurePosixPath

from sb_checks.core import FileContext, Violation, matches_any

BANNED_NAMES = frozenset({"utils", "helpers", "common", "misc"})


class BannedModuleNamesCheck:
    check_id = "banned-module-names"
    description = "No modules/packages named utils, helpers, common or misc."
    patterns = ("libs/**/*.py", "services/**/*.py", "tools/**/*.py")

    def applies_to(self, path: PurePosixPath) -> bool:
        return matches_any(path, self.patterns)

    def run(self, ctx: FileContext) -> Iterator[Violation]:
        name = ctx.path.parent.name if ctx.path.name == "__init__.py" else ctx.path.stem
        if name in BANNED_NAMES:
            yield ctx.violation(
                self.check_id, 1, f"module name '{name}' says nothing; name it after what it does"
            )
