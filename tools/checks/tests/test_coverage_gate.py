"""Exercise the real Make coverage gate on tiny repositories, including unimported code."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("gap", ["none", "branch", "unimported", "namespace", "service"])
def test_coverage_gate_measures_all_logic(tmp_path: Path, gap: str) -> None:
    shutil.copy(REPO / "Makefile", tmp_path)
    (tmp_path / "mk").mkdir()
    if (REPO / "mk/quality.mk").exists():
        shutil.copy(REPO / "mk/quality.mk", tmp_path / "mk")
    if (REPO / ".coveragerc").exists():
        shutil.copy(REPO / ".coveragerc", tmp_path)
    source = tmp_path / "libs/py/sb_kernel/src"
    source.mkdir(parents=True)
    (source / "probe.py").write_text(
        "def choose(value):\n    if value:\n        return 1\n    return 2\n"
    )
    if gap == "unimported":
        (source / "forgotten.py").write_text("def untested():\n    return 3\n")
    if gap == "namespace":
        nested = source / "namespace"
        nested.mkdir()
        (nested / "forgotten.py").write_text("def untested():\n    return 3\n")
    if gap == "service":
        domain = tmp_path / "services/payments/src/payments/domain"
        domain.mkdir(parents=True)
        (domain / "forgotten.py").write_text("def untested():\n    return 3\n")
    test = "from probe import choose\ndef test_choose():\n    assert choose(True) == 1\n"
    if gap != "branch":
        test += "    assert choose(False) == 2\n"
    (tmp_path / "test_probe.py").write_text(test)
    # Use the installed coverage in this interpreter without requiring a nested uv workspace.
    launcher = tmp_path / "uv.py"
    launcher.write_text(
        "import subprocess, sys\n"
        "assert sys.argv[1:3] == ['run', 'coverage']\n"
        "sys.exit(subprocess.call([sys.executable, '-m', *sys.argv[2:]]))\n"
    )
    result = subprocess.run(
        ["make", "coverage", f"UV={sys.executable} {launcher}"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        env={**os.environ, "PYTHONPATH": str(source), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
    )
    output = result.stdout + result.stderr
    assert "No rule to make target" not in output, output
    assert "No module named coverage" not in output, output
    if gap == "none":
        assert result.returncode == 0, output
        assert "100.00%" in output, output
    else:
        assert result.returncode != 0, output
        assert "Coverage failure" in output, output
    assert (tmp_path / "coverage.xml").is_file(), output
