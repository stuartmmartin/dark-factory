import ast
from pathlib import Path

from sb_graph.imports import actual_internal_deps, imported_roots
from sb_graph.workspace import discover_members


def test_imported_roots_collects_absolute_imports_only() -> None:
    source = "import a.b\nfrom c.d import e\nfrom . import f\nfrom .g import h\nimport i as j\n"
    assert imported_roots(ast.parse(source)) == {"a", "c", "i"}


def test_actual_internal_deps_scans_src_only(workspace: Path, add_member) -> None:
    add_member("libs/py/sb_kernel", "sb-kernel", files={"src/sb_kernel/__init__.py": ""})
    add_member(
        "services/ledger",
        "ledger",
        files={
            "src/ledger/app.py": "import sb_kernel\nimport fastapi\nimport ledger.x\n",
            "tests/test_app.py": "import pytest_only_thing\n",
        },
    )
    members = discover_members(workspace)
    ledger = next(m for m in members if m.name == "ledger")
    assert actual_internal_deps(workspace, ledger, members) == ("sb-kernel",)
