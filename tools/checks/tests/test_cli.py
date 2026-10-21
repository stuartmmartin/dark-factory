from collections.abc import Iterator, Sequence
from pathlib import Path, PurePosixPath

import pytest

from sb_checks import cli
from sb_checks.core import FileContext, Violation


class FlagEverythingCheck:
    check_id = "flag-all"
    description = "test double: one violation per file"

    def applies_to(self, path: PurePosixPath) -> bool:
        del path
        return True

    def run(self, ctx: FileContext) -> Iterator[Violation]:
        yield ctx.violation(self.check_id, 1, "flagged")


def test_list_prints_every_check(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["list"]) == 0
    out = capsys.readouterr().out
    for check in cli.ALL_CHECKS:
        assert check.check_id in out


def test_run_on_clean_tree_exits_zero(tmp_path: Path) -> None:
    assert cli.main(["run", "--root", str(tmp_path)]) == 0


def test_run_with_violations_exits_one_and_prints_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "x.py").write_text("x = 1\n")
    monkeypatch.setattr(cli, "ALL_CHECKS", (FlagEverythingCheck(),))
    assert cli.main(["run", "--root", str(tmp_path)]) == 1
    assert "tools/x.py:1: [flag-all] flagged" in capsys.readouterr().out


def test_run_with_malformed_allowlist_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    allowlist = tmp_path / "tools" / "checks" / "allowlist.toml"
    allowlist.parent.mkdir(parents=True)
    allowlist.write_text("[[allow]\n")
    assert cli.main(["run", "--root", str(tmp_path)]) == 2
    assert "allowlist.toml" in capsys.readouterr().err


class _DoctorProbe:
    def __init__(self, tools: set[str], daemon_ok: bool = True) -> None:
        self.tools, self.daemon_ok = tools, daemon_ok

    def which(self, tool: str) -> str | None:
        return f"/bin/{tool}" if tool in self.tools else None

    def run(self, argv: Sequence[str]) -> tuple[int, str]:
        return (1, "down") if list(argv) == ["docker", "info"] and not self.daemon_ok else (0, "")

    def port_free(self, port: int) -> bool:
        del port
        return True

    def exists(self, path: str) -> bool:
        del path
        return True


def test_doctor_exits_one_with_cross_line_on_failure(capsys: pytest.CaptureFixture[str]) -> None:
    probe = _DoctorProbe(
        {"uv", "docker", "mise", "gitleaks", "pyright-langserver"}, daemon_ok=False
    )
    assert cli.main(["doctor"], probe=probe) == 1
    assert "✘ docker daemon" in capsys.readouterr().out


def test_doctor_exits_zero_with_only_warnings(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["doctor"], probe=_DoctorProbe({"uv", "docker"})) == 0
    out = capsys.readouterr().out
    assert "! mise" in out
    assert "✘" not in out
