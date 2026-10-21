"""Each use case lists its business rules R1..Rn; each rule has a test named test_R<n>_*.

This is the human review contract: a reviewer reads the use case docstring and the matching
test file, and can see every business rule with the test that pins it.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import PurePosixPath

from sb_checks.core import FileContext, Violation, matches_any

RULE_RE = re.compile(r"^\s*(?:-\s*)?R(\d+):", re.MULTILINE)
TEST_RE = re.compile(r"^test_R(\d+)_")


def _tested_rules(tree: ast.Module) -> set[int]:
    tested: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            match = TEST_RE.match(node.name)
            if match:
                tested.add(int(match.group(1)))
    return tested


class UseCaseRulesCheck:
    check_id = "use-case-rules"
    description = "Use case docstrings list R<n>: rules; each has a test_R<n>_* unit test."
    patterns = ("services/*/src/*/application/use_cases/*.py",)

    def applies_to(self, path: PurePosixPath) -> bool:
        return path.name != "__init__.py" and matches_any(path, self.patterns)

    def run(self, ctx: FileContext) -> Iterator[Violation]:
        docstring = ast.get_docstring(ctx.tree) or ""
        rules = {int(n) for n in RULE_RE.findall(docstring)}
        if not rules:
            yield ctx.violation(
                self.check_id, 1, "module docstring must list business rules as 'R1: ...' lines"
            )
            return
        test_rel = (
            PurePosixPath(*ctx.path.parts[:2])
            / "tests"
            / "unit"
            / "use_cases"
            / f"test_{ctx.path.stem}.py"
        )
        test_file = ctx.root / test_rel
        if not test_file.is_file():
            yield ctx.violation(self.check_id, 1, f"missing rule tests: {test_rel}")
            return
        try:
            test_tree = ast.parse(test_file.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            yield Violation(test_rel, exc.lineno or 1, "syntax-error", exc.msg)
            return
        tested = _tested_rules(test_tree)
        for number in sorted(rules - tested):
            yield ctx.violation(
                self.check_id, 1, f"R{number} has no test named test_R{number}_* in {test_rel}"
            )
        for number in sorted(tested - rules):
            yield Violation(
                test_rel,
                1,
                self.check_id,
                f"test_R{number}_* tests a rule not listed in {ctx.path} docstring",
            )
