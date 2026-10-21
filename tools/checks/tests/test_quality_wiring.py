"""Required coverage and named local equivalents must remain wired into the CI gate."""

import tomllib
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]


def test_coverage_is_a_required_ci_job() -> None:
    jobs = yaml.safe_load((REPO / ".github/workflows/ci.yml").read_text())["jobs"]
    assert "coverage" in jobs["ci-ok"]["needs"]
    assert any(step.get("run") == "make coverage" for step in jobs["coverage"]["steps"])


def test_check_covers_openapi_and_coverage() -> None:
    target = next(
        line for line in (REPO / "Makefile").read_text().splitlines() if line.startswith("check:")
    )
    assert "coverage" in target
    assert "openapi-check" in target
    assert "Everything CI runs" not in target


def test_ci_uses_shared_local_audit_and_secret_commands() -> None:
    jobs = yaml.safe_load((REPO / ".github/workflows/ci.yml").read_text())["jobs"]
    assert any(step.get("run") == "make audit" for step in jobs["audit"]["steps"])
    assert any(step.get("run") == "make secrets-check" for step in jobs["preflight"]["steps"])


def test_warnings_are_errors_without_a_blanket_allowlist() -> None:
    config = tomllib.loads((REPO / "pyproject.toml").read_text())
    assert config["tool"]["pytest"]["ini_options"]["filterwarnings"] == ["error"]
