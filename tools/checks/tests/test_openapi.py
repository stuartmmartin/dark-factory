"""`sb-checks openapi`: render a service's OpenAPI document and write or drift-check it.

A throwaway service package stands in for a real one: sb_checks never depends on services.
"""

import json
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from sb_checks import cli, openapi

SERVICE = "sb_checks_openapi_fake_service"

_BOOTSTRAP = """
class _App:
    def __init__(self, settings):
        self.settings = settings

    def openapi(self):
        return {"paths": {"/b": {}, "/a": {}}, "info": {"title": self.settings["environment"]}}


def build_api(settings):
    return _App(settings)
"""

_SETTINGS = """
class Settings(dict):
    def __init__(self, **values):
        super().__init__(values)
"""


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    package = tmp_path / "src" / SERVICE
    (package / "infrastructure").mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "bootstrap.py").write_text(_BOOTSTRAP)
    (package / "infrastructure" / "__init__.py").write_text("")
    (package / "infrastructure" / "settings.py").write_text(_SETTINGS)
    monkeypatch.syspath_prepend(str(tmp_path / "src"))
    yield tmp_path
    for name in [m for m in sys.modules if m.split(".")[0] == SERVICE]:
        del sys.modules[name]


def _contract(root: Path) -> Path:
    return root / "contracts" / "openapi" / f"{SERVICE}.json"


def test_render_builds_the_app_with_test_settings_and_sorts_keys(root: Path) -> None:
    rendered = openapi.render(SERVICE)
    assert rendered.endswith("\n")
    assert json.loads(rendered) == {"info": {"title": "test"}, "paths": {"/a": {}, "/b": {}}}
    assert rendered.index('"info"') < rendered.index('"paths"')
    assert rendered.index('"/a"') < rendered.index('"/b"')


def test_test_settings_use_dev_auth_in_the_test_environment() -> None:
    assert openapi.TEST_SETTINGS["environment"] == "test"
    assert openapi.TEST_SETTINGS["auth_mode"] == "dev"


def test_write_then_check_passes(root: Path) -> None:
    assert cli.main(["openapi", "--service", SERVICE, "--root", str(root), "--write"]) == 0
    assert _contract(root).read_text() == openapi.render(SERVICE)
    assert cli.main(["openapi", "--service", SERVICE, "--root", str(root), "--check"]) == 0


def test_check_fails_on_drift(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _contract(root).parent.mkdir(parents=True)
    _contract(root).write_text('{"paths": {}}\n')
    assert cli.main(["openapi", "--service", SERVICE, "--root", str(root), "--check"]) == 1
    assert "make openapi" in capsys.readouterr().err


def test_check_fails_when_the_contract_is_missing(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["openapi", "--service", SERVICE, "--root", str(root), "--check"]) == 1
    assert "missing" in capsys.readouterr().err


def test_check_and_write_are_mutually_exclusive(root: Path) -> None:
    with pytest.raises(SystemExit):
        cli.main(["openapi", "--service", SERVICE, "--root", str(root), "--check", "--write"])


@pytest.mark.parametrize("name", ["../etc", "os.path", "Ledger", ""])
def test_service_must_be_a_plain_package_name(root: Path, name: str) -> None:
    assert cli.main(["openapi", "--service", name, "--root", str(root), "--check"]) == 2
