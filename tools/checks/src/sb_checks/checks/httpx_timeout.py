"""Every outbound httpx call or client carries an explicit timeout (external I/O AP-1)."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import PurePosixPath

from sb_checks.core import FileContext, Violation, matches_any

_HTTPX_CALLS = frozenset(
    {
        "get",
        "post",
        "put",
        "patch",
        "delete",
        "head",
        "options",
        "request",
        "stream",
        "Client",
        "AsyncClient",
    }
)


class HttpxTimeoutCheck:
    check_id = "httpx-timeout"
    description = "httpx.<call>/Client/AsyncClient must pass timeout= (aliases resolved)."
    patterns = ("libs/py/*/src/**/*.py", "services/*/src/**/*.py")

    def applies_to(self, path: PurePosixPath) -> bool:
        return matches_any(path, self.patterns)

    def run(self, ctx: FileContext) -> Iterator[Violation]:
        modules, names = _httpx_bindings(ctx.tree)
        for node in ast.walk(ctx.tree):
            if not isinstance(node, ast.Call):
                continue
            call = _httpx_call(node.func, modules, names)
            if call is None:
                continue
            keywords = {keyword.arg for keyword in node.keywords}
            if None in keywords:  # **kwargs: cannot tell statically (documented blind spot)
                continue
            if "timeout" not in keywords:
                yield ctx.violation(self.check_id, node, f"httpx.{call}() without timeout=")


def _httpx_bindings(tree: ast.Module) -> tuple[set[str], dict[str, str]]:
    """Local names bound to the httpx module, and local names bound to policed httpx callables."""
    modules = {"httpx"}
    names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.asname for a in node.names if a.name == "httpx" and a.asname)
        elif isinstance(node, ast.ImportFrom) and node.module == "httpx" and node.level == 0:
            names.update((a.asname or a.name, a.name) for a in node.names if a.name in _HTTPX_CALLS)
    return modules, names


def _httpx_call(func: ast.expr, modules: set[str], names: dict[str, str]) -> str | None:
    if (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id in modules
        and func.attr in _HTTPX_CALLS
    ):
        return func.attr
    if isinstance(func, ast.Name):
        return names.get(func.id)
    return None
