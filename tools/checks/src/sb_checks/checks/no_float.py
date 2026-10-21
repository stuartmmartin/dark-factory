"""Business math must use Decimal (sb_kernel.Money), never float (ADR-0015)."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import PurePosixPath

from sb_checks.core import FileContext, Violation, matches_any


class NoFloatCheck:
    check_id = "no-float"
    description = "No float in domain/, application/ or sb_kernel: use Decimal / sb_kernel.Money."
    patterns = (
        "services/*/src/*/domain/**/*.py",
        "services/*/src/*/application/**/*.py",
        "libs/py/sb_kernel/src/**/*.py",
    )

    def applies_to(self, path: PurePosixPath) -> bool:
        return matches_any(path, self.patterns)

    def run(self, ctx: FileContext) -> Iterator[Violation]:
        for node in ast.walk(ctx.tree):
            if isinstance(node, ast.Name) and node.id == "float":
                yield ctx.violation(self.check_id, node, "`float` used; use Decimal / Money")
            elif isinstance(node, ast.Constant) and isinstance(node.value, float):
                yield ctx.violation(
                    self.check_id, node, f"float literal {node.value!r}; use Decimal('...')"
                )
