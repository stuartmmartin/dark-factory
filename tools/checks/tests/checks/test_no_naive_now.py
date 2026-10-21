import pytest

from sb_checks.checks.no_naive_now import NoNaiveNowCheck

APP = "services/ledger/src/ledger/application/use_cases/post.py"


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("from datetime import datetime\ndatetime.now()\n", id="datetime.now"),
        pytest.param(
            "import datetime\ndatetime.datetime.utcnow()\n", id="datetime.datetime.utcnow"
        ),
        pytest.param("from datetime import date\ndate.today()\n", id="date.today"),
        pytest.param("import time\ntime.time()\n", id="time.time"),
    ],
)
def test_flags_wall_clock_reads(run_check, source: str) -> None:
    [v] = run_check(NoNaiveNowCheck(), APP, source)
    assert v.check_id == "no-naive-now"
    assert v.line == 2


def test_clock_module_is_exempt(run_check) -> None:
    rel = "libs/py/sb_kernel/src/sb_kernel/clock.py"
    assert run_check(NoNaiveNowCheck(), rel, "import datetime\ndatetime.datetime.now()\n") == []


def test_injected_clock_is_fine(run_check) -> None:
    assert run_check(NoNaiveNowCheck(), APP, "def f(self):\n    return self.clock.now()\n") == []


def test_tests_are_not_checked(run_check) -> None:
    rel = "services/ledger/tests/unit/test_x.py"
    assert run_check(NoNaiveNowCheck(), rel, "import time\ntime.time()\n") == []


class TestDocumentedBlindSpots:
    def test_aliased_import_is_not_caught(self, run_check) -> None:
        source = "from datetime import datetime as dt\ndt.now()\n"
        assert run_check(NoNaiveNowCheck(), APP, source) == []
