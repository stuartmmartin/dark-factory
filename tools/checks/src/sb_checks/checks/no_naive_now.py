"""Never read the wall clock directly; inject the sb_kernel Clock port instead."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import PurePosixPath

from sb_checks.core import FileContext, Violation, matches_any

_BANNED = frozenset(
    {
        ("datetime", "now"),
        ("datetime", "utcnow"),
        ("datetime", "today"),
        ("date", "today"),
        ("time", "time"),
    }
)


def _owner_name(expr: ast.expr) -> str | None:
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        return expr.attr
    return None


class NoNaiveNowCheck:
    check_id = "no-naive-now"
    description = "No datetime.now()/date.today()/time.time() in src: inject a Clock."
    patterns = ("libs/py/*/src/**/*.py", "services/*/src/**/*.py")
    exempt = ("**/clock.py",)

    def applies_to(self, path: PurePosixPath) -> bool:
        return matches_any(path, self.patterns) and not matches_any(path, self.exempt)

    def run(self, ctx: FileContext) -> Iterator[Violation]:
        for node in ast.walk(ctx.tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                key = (_owner_name(node.func.value), node.func.attr)
                if key in _BANNED:
                    yield ctx.violation(
                        self.check_id, node, f"{key[0]}.{key[1]}() reads the wall clock; use Clock"
                    )
