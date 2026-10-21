import pytest

from sb_checks.checks.banned_module_names import BannedModuleNamesCheck


@pytest.mark.parametrize(
    "rel",
    [
        "libs/py/sb_x/src/sb_x/utils.py",
        "services/ledger/src/ledger/helpers/__init__.py",
        "tools/graph/src/sb_graph/common.py",
        "services/ledger/tests/misc.py",
    ],
)
def test_flags_meaningless_module_names(run_check, rel: str) -> None:
    [v] = run_check(BannedModuleNamesCheck(), rel, "")
    assert v.check_id == "banned-module-names"
    assert v.line == 1


def test_descriptive_names_are_fine(run_check) -> None:
    assert run_check(BannedModuleNamesCheck(), "libs/py/sb_x/src/sb_x/money.py", "") == []


class TestDocumentedBlindSpots:
    def test_banned_name_as_a_directory_is_not_caught(self, run_check) -> None:
        # Mitigation: only the module itself or its package __init__ is checked, not a
        # directory that happens to share a banned name while holding a real module.
        rel = "libs/py/sb_x/src/sb_x/utils/money.py"
        assert run_check(BannedModuleNamesCheck(), rel, "") == []
