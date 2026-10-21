import ast
from pathlib import Path, PurePosixPath

import pytest

from sb_checks.core import FileContext, Violation, iter_python_files, matches_any


def test_violation_renders_path_line_and_check_id() -> None:
    violation = Violation(PurePosixPath("a/b.py"), 3, "no-float", "bad")
    assert violation.render() == "a/b.py:3: [no-float] bad"


def test_violations_sort_by_path_then_line() -> None:
    a = Violation(PurePosixPath("b.py"), 1, "x", "m")
    b = Violation(PurePosixPath("a.py"), 9, "x", "m")
    c = Violation(PurePosixPath("a.py"), 2, "x", "m")
    assert sorted([a, b, c]) == [c, b, a]


def test_file_context_violation_uses_node_line_or_explicit_line() -> None:
    tree = ast.parse("x = 1\ny = 2\n")
    ctx = FileContext(Path("/repo"), PurePosixPath("m.py"), "", tree)
    assert ctx.violation("c", tree.body[1], "m").line == 2
    assert ctx.violation("c", 7, "m").line == 7


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param("services/ledger/src/ledger/domain/money.py", True, id="direct-child"),
        pytest.param("services/ledger/src/ledger/domain/sub/x.py", True, id="nested"),
        pytest.param("services/ledger/src/ledger/infrastructure/x.py", False, id="other-layer"),
    ],
)
def test_matches_any_supports_double_star(path: str, expected: bool) -> None:
    pattern = "services/*/src/*/domain/**/*.py"
    assert matches_any(PurePosixPath(path), [pattern]) is expected


def test_iter_python_files_skips_venv_pycache_fixtures_and_non_code_roots(tmp_path: Path) -> None:
    for rel in [
        "tools/a/src/a/x.py",
        "tools/a/.venv/lib/y.py",
        "tools/a/tests/fixtures/z.py",
        "services/s/src/s/__pycache__/q.py",
        "docs/n.py",
    ]:
        file = tmp_path / rel
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("")
    assert list(iter_python_files(tmp_path)) == [PurePosixPath("tools/a/src/a/x.py")]
