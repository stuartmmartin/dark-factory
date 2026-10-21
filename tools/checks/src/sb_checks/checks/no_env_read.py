"""Environment variables are read only in the settings module (pydantic-settings).

That is `infrastructure/settings.py` in a service and the top-level `settings.py` of a lib
package; a `settings.py` anywhere else (for example `domain/settings.py`) is still flagged.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import PurePosixPath

from sb_checks.core import FileContext, Violation, matches_any

_BANNED_ATTRS = frozenset({"getenv", "getenvb", "environ", "environb", "putenv"})


class NoEnvReadCheck:
    check_id = "no-env-read"
    description = "No os.getenv/os.environ outside infrastructure/settings.py (lib: settings.py)."
    patterns = ("libs/py/*/src/**/*.py", "services/*/src/**/*.py")
    exempt = (
        "services/*/src/*/infrastructure/settings.py",
        "libs/py/*/src/*/settings.py",
    )

    def applies_to(self, path: PurePosixPath) -> bool:
        return matches_any(path, self.patterns) and not matches_any(path, self.exempt)

    def run(self, ctx: FileContext) -> Iterator[Violation]:
        message = (
            "environment read outside the settings module; add a field to Settings "
            "(infrastructure/settings.py) instead"
        )
        for node in ast.walk(ctx.tree):
            if _is_banned_os_attribute(node) or _is_banned_os_import(node):
                yield ctx.violation(self.check_id, node, message)


def _is_banned_os_attribute(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
        and node.attr in _BANNED_ATTRS
    )


def _is_banned_os_import(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.ImportFrom)
        and node.module == "os"
        and any(alias.name in _BANNED_ATTRS for alias in node.names)
    )
