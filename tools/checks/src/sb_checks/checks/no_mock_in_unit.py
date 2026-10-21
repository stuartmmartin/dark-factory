"""Unit tests use in-memory fakes of ports (tests/<service>_fakes.py), never mocks.

Fakes implement the Protocol, so signature drift breaks them; mocks accept anything and
produce tautological tests. Mocks remain allowed in integration tests at true edges.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import PurePosixPath

from sb_checks.core import FileContext, Violation, matches_any

_MOCK_MODULES = frozenset({"unittest.mock", "mock", "pytest_mock"})
_MESSAGE = "mock in a unit test; use an in-memory fake of the port (tests/<service>_fakes.py)"


def _argument_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    args = node.args
    return {a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)}


class NoMockInUnitCheck:
    check_id = "no-mock-in-unit"
    description = "No unittest.mock / pytest-mock in tests/unit: use fakes."
    patterns = ("**/tests/unit/**/*.py",)

    def applies_to(self, path: PurePosixPath) -> bool:
        return matches_any(path, self.patterns)

    def run(self, ctx: FileContext) -> Iterator[Violation]:
        for node in ast.walk(ctx.tree):
            if _imports_mock_module(node) or _has_mocker_fixture(node):
                yield ctx.violation(self.check_id, node, _MESSAGE)


def _imports_mock_module(node: ast.AST) -> bool:
    if isinstance(node, ast.Import):
        return any(alias.name in _MOCK_MODULES for alias in node.names)
    if isinstance(node, ast.ImportFrom) and node.level == 0:
        module = node.module or ""
        from_unittest = module == "unittest" and any(a.name == "mock" for a in node.names)
        return module in _MOCK_MODULES or from_unittest
    return False


def _has_mocker_fixture(node: ast.AST) -> bool:
    return isinstance(
        node, (ast.FunctionDef, ast.AsyncFunctionDef)
    ) and "mocker" in _argument_names(node)
