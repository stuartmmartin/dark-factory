import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest

from sb_checks.core import Check, Violation
from sb_checks.runner import run_checks

RunCheck = Callable[..., list[Violation]]


@pytest.fixture
def run_check(tmp_path: Path) -> RunCheck:
    def _run(
        check: Check, rel: str, source: str, extra: dict[str, str] | None = None
    ) -> list[Violation]:
        for file_rel, file_source in {rel: source, **(extra or {})}.items():
            file = tmp_path / file_rel
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(textwrap.dedent(file_source))
        return run_checks(tmp_path, [check])

    return _run
