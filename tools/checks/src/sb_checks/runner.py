"""Run a set of checks over every Python file in the repo's code roots."""

from __future__ import annotations

import ast
from collections.abc import Sequence
from pathlib import Path

from sb_checks.allowlist import AllowEntry, apply_allowlist
from sb_checks.core import AnyCheck, Check, FileContext, RepoCheck, Violation, iter_python_files


def run_checks(
    root: Path, checks: Sequence[AnyCheck], allowlist: Sequence[AllowEntry] = ()
) -> list[Violation]:
    violations: list[Violation] = []
    file_checks: list[Check] = []
    for check in checks:
        if isinstance(check, RepoCheck):
            violations.extend(check.scan(root))
        else:
            file_checks.append(check)
    for rel in iter_python_files(root):
        applicable = [check for check in file_checks if check.applies_to(rel)]
        if not applicable:
            continue
        source = (root / rel).read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(rel))
        except SyntaxError as exc:
            violations.append(Violation(rel, exc.lineno or 1, "syntax-error", exc.msg))
            continue
        ctx = FileContext(root, rel, source, tree)
        for check in applicable:
            violations.extend(check.run(ctx))
    return apply_allowlist(violations, allowlist)
