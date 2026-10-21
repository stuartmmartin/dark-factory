import pytest

from sb_checks.checks.no_env_read import NoEnvReadCheck

SRC = "services/ledger/src/ledger/infrastructure/db/engine.py"


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("import os\nos.getenv('X')\n", id="getenv"),
        pytest.param("import os\nos.environ['X']\n", id="environ"),
        pytest.param("from os import environ\n", id="from-import"),
    ],
)
def test_flags_env_reads_outside_settings(run_check, source: str) -> None:
    [v] = run_check(NoEnvReadCheck(), SRC, source)
    assert v.check_id == "no-env-read"


@pytest.mark.parametrize(
    "rel",
    [
        "services/ledger/src/ledger/infrastructure/settings.py",
        "libs/py/sb_db/src/sb_db/settings.py",
    ],
)
def test_settings_modules_are_exempt(run_check, rel: str) -> None:
    assert run_check(NoEnvReadCheck(), rel, "import os\nos.getenv('X')\n") == []


@pytest.mark.parametrize(
    "rel",
    [
        "services/ledger/src/ledger/domain/settings.py",
        "services/ledger/src/ledger/application/settings.py",
        "services/ledger/src/ledger/infrastructure/db/settings.py",
        "libs/py/sb_db/src/sb_db/engine/settings.py",
    ],
)
def test_settings_py_elsewhere_is_flagged(run_check, rel: str) -> None:
    [v] = run_check(NoEnvReadCheck(), rel, "import os\nos.getenv('X')\n")
    assert v.check_id == "no-env-read"


class TestDocumentedBlindSpots:
    def test_aliased_os_is_not_caught(self, run_check) -> None:
        assert run_check(NoEnvReadCheck(), SRC, "import os as o\no.getenv('X')\n") == []
