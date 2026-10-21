import pytest

from sb_checks.checks.no_mock_in_unit import NoMockInUnitCheck

UNIT = "services/ledger/tests/unit/use_cases/test_post.py"


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("from unittest.mock import MagicMock\n", id="from-unittest.mock"),
        pytest.param("import unittest.mock\n", id="import-unittest.mock"),
        pytest.param("from unittest import mock\n", id="from-unittest-import-mock"),
        pytest.param("import pytest_mock\n", id="pytest_mock"),
        pytest.param("def test_x(mocker):\n    pass\n", id="mocker-fixture"),
    ],
)
def test_flags_mocks_in_unit_tests(run_check, source: str) -> None:
    [v] = run_check(NoMockInUnitCheck(), UNIT, source)
    assert v.check_id == "no-mock-in-unit"


def test_integration_tests_may_mock(run_check) -> None:
    rel = "services/ledger/tests/integration/http/test_routes.py"
    assert run_check(NoMockInUnitCheck(), rel, "from unittest.mock import AsyncMock\n") == []


def test_fakes_are_fine(run_check) -> None:
    source = "from tests_support import InMemoryJournal\n\ndef test_x():\n    InMemoryJournal()\n"
    assert run_check(NoMockInUnitCheck(), UNIT, source) == []


class TestDocumentedBlindSpots:
    def test_dynamic_import_is_not_caught(self, run_check) -> None:
        source = "import importlib\nm = importlib.import_module('unittest.mock')\n"
        assert run_check(NoMockInUnitCheck(), UNIT, source) == []
