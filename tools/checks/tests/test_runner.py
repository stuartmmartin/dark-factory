import ast
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

from sb_checks.core import FileContext, Violation, matches_any
from sb_checks.runner import run_checks


class FlagPassCheck:
    check_id = "flag-pass"
    description = "test double: flags every `pass` statement under tools/"

    def applies_to(self, path: PurePosixPath) -> bool:
        return matches_any(path, ["tools/**/*.py"])

    def run(self, ctx: FileContext) -> Iterator[Violation]:
        for node in ast.walk(ctx.tree):
            if isinstance(node, ast.Pass):
                yield ctx.violation(self.check_id, node, "pass found")


def _write(root: Path, rel: str, source: str) -> None:
    file = root / rel
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(source)


def test_runs_applicable_checks_and_sorts_violations(tmp_path: Path) -> None:
    _write(tmp_path, "tools/t/src/t/b.py", "def f():\n    pass\n")
    _write(tmp_path, "tools/t/src/t/a.py", "pass\n")
    _write(tmp_path, "services/s/src/s/c.py", "pass\n")
    violations = run_checks(tmp_path, [FlagPassCheck()])
    assert [v.render() for v in violations] == [
        "tools/t/src/t/a.py:1: [flag-pass] pass found",
        "tools/t/src/t/b.py:2: [flag-pass] pass found",
    ]


def test_syntax_error_is_reported_and_other_files_still_checked(tmp_path: Path) -> None:
    _write(tmp_path, "tools/t/src/t/broken.py", "def (:\n")
    _write(tmp_path, "tools/t/src/t/ok.py", "pass\n")
    violations = run_checks(tmp_path, [FlagPassCheck()])
    assert [v.check_id for v in violations] == ["syntax-error", "flag-pass"]
