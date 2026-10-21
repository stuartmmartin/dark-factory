import pytest

from sb_checks.checks.no_member_tool_config import NoMemberToolConfigCheck

MEMBER = "tools/x/pyproject.toml"


def test_member_ruff_table_is_flagged(run_check) -> None:
    source = """
        [project]
        name = "x"

        [tool.ruff.lint]
        select = []
        """
    [v] = run_check(NoMemberToolConfigCheck(), MEMBER, source)
    assert v.check_id == "no-member-tool-config"
    assert str(v.path) == MEMBER
    assert v.line == 5
    assert "root ruff.toml / pyrightconfig.json" in v.message


@pytest.mark.parametrize("table", ["pyright", "mypy", "ruff"])
def test_each_banned_tool_table_is_flagged(run_check, table: str) -> None:
    [v] = run_check(NoMemberToolConfigCheck(), MEMBER, f"[tool.{table}]\nx = 1\n")
    assert f"[tool.{table}]" in v.message


@pytest.mark.parametrize(
    "rel",
    ["libs/py/sb_x/pyproject.toml", "services/ledger/pyproject.toml", "tools/x/pyproject.toml"],
)
def test_all_member_roots_are_scanned(run_check, rel: str) -> None:
    assert len(run_check(NoMemberToolConfigCheck(), rel, "[tool.ruff]\n")) == 1


def test_member_with_only_project_passes(run_check) -> None:
    source = '[project]\nname = "x"\n\n[tool.pytest.ini_options]\naddopts = []\n'
    assert run_check(NoMemberToolConfigCheck(), MEMBER, source) == []


def test_root_pyproject_is_not_a_member(run_check) -> None:
    assert run_check(NoMemberToolConfigCheck(), "pyproject.toml", "[tool.ruff]\n") == []


class TestDocumentedBlindSpots:
    def test_sibling_ruff_toml_file_is_not_caught(self, run_check) -> None:
        extra = {"tools/x/ruff.toml": "[lint]\nselect = []\n"}
        assert run_check(NoMemberToolConfigCheck(), MEMBER, '[project]\nname = "x"\n', extra) == []
