"""Make discovers every service through the graph, failing closed if discovery fails."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("failure", ["none", "discovery", "service"])
def test_make_openapi_discovers_services(tmp_path: Path, failure: str) -> None:
    shutil.copy(REPO / "Makefile", tmp_path)
    (tmp_path / "mk").mkdir()
    shutil.copy(REPO / "mk/python.mk", tmp_path / "mk")
    launcher = tmp_path / "uv.py"
    launcher.write_text(
        "import pathlib, sys\n"
        f"failure = {failure!r}\n"
        "args = sys.argv[1:]\n"
        "if args == ['run', 'sb-graph', 'members', '--kind', 'service', '--format', 'imports']:\n"
        "    print('ledger\\ninvoices')\n"
        "    sys.exit(2 if failure == 'discovery' else 0)\n"
        "assert args[:3] == ['run', 'sb-checks', 'openapi'], args\n"
        "assert args[3] == '--service' and args[5] == '--check', args\n"
        "with pathlib.Path('calls').open('a') as file:\n"
        "    file.write(args[4] + '\\n')\n"
        "sys.exit(1 if failure == 'service' and args[4] == 'invoices' else 0)\n"
    )
    result = subprocess.run(
        ["make", "openapi-check", f"UV={sys.executable} {launcher}"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert (result.returncode == 0) == (failure == "none"), result.stdout + result.stderr
    calls = tmp_path / "calls"
    if failure == "discovery":
        assert not calls.exists()
    else:
        assert calls.read_text().splitlines() == ["ledger", "invoices"]
