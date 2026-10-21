"""The rendered ledger overlays: only the API Deployment gets the admin credentials Secret."""

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
ADMIN_ENV_FROM = "ledger-admin-secrets"


def _render(env: str) -> list[dict[str, Any]]:
    if shutil.which("kustomize") is None and shutil.which("mise") is None:
        pytest.skip("kustomize is not installed (make bootstrap)")
    result = subprocess.run(
        ["make", "--no-print-directory", "k8s-render", "SVC=ledger", f"ENV={env}"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return [cast(dict[str, Any], d) for d in yaml.safe_load_all(result.stdout) if d]


def _secret_refs(doc: dict[str, Any]) -> set[str]:
    containers = doc["spec"]["template"]["spec"]["containers"]
    return {
        ref["secretRef"]["name"]
        for container in containers
        for ref in container.get("envFrom", [])
        if "secretRef" in ref
    }


def _workloads(docs: list[dict[str, Any]]) -> dict[str, set[str]]:
    return {
        d["metadata"]["name"]: _secret_refs(d) for d in docs if d["kind"] in {"Deployment", "Job"}
    }


def test_dev_gives_the_admin_secret_to_the_api_only() -> None:
    holders = {name for name, refs in _workloads(_render("dev")).items() if ADMIN_ENV_FROM in refs}
    assert holders == {"ledger-api"}


def test_prod_mounts_no_admin_secret() -> None:
    assert all(ADMIN_ENV_FROM not in refs for refs in _workloads(_render("prod")).values())


@pytest.mark.parametrize("renderer", ["false", "true"])
def test_validation_refuses_failed_or_empty_render(renderer: str) -> None:
    # A successful downstream validator must not hide failure or empty renderer output.
    result = subprocess.run(
        ["make", "k8s-validate", f"KUSTOMIZE={renderer}", "KUBECONFORM=true"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    if renderer == "true":
        assert "empty render" in result.stderr


@pytest.mark.parametrize("document", ["# comment only\n", "---\n", " \n"])
def test_validation_refuses_render_without_resources(tmp_path: Path, document: str) -> None:
    renderer = tmp_path / "render.sh"
    renderer.write_text("#!/bin/sh\ncat <<'MANIFEST'\n" + document + "MANIFEST\n")
    renderer.chmod(0o755)
    result = subprocess.run(
        ["make", "k8s-validate", f"KUSTOMIZE={renderer}", "KUBECONFORM=true"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "empty render" in result.stderr


@pytest.mark.parametrize(
    "document",
    [
        "apiVersion: v1\nkind: ConfigMap\nmetadata: {name: broken}\ndata: {key: [not-a-string]}\n",
        "apiVersion: unsupported/v1\nkind: Unknown\nmetadata: {name: broken}\n",
        "apiVersion: [malformed\nkind: ConfigMap\n",
    ],
)
@pytest.mark.integration
@pytest.mark.allow_network(reason="kubeconform fetches Kubernetes schemas")
def test_real_validator_rejects_invalid_render(tmp_path: Path, document: str) -> None:
    # No skip: make bootstrap supplies the validator, and failure to run it must fail this gate.
    renderer = tmp_path / "render.sh"
    renderer.write_text("#!/bin/sh\ncat <<'MANIFEST'\n" + document + "MANIFEST\n")
    renderer.chmod(0o755)
    result = subprocess.run(
        ["make", "k8s-validate", f"KUSTOMIZE={renderer}"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert re.search(r"(?:Invalid|Errors): [1-9]", result.stdout), result.stdout + result.stderr


@pytest.mark.integration
@pytest.mark.allow_network(reason="kubeconform fetches Kubernetes schemas")
def test_real_overlays_validate_nonzero_resources() -> None:
    result = subprocess.run(
        ["make", "k8s-validate"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    counts = re.findall(r"Summary: (\d+) resource", result.stdout)
    assert counts, result.stdout
    assert all(int(count) > 0 for count in counts), result.stdout


def test_validation_propagates_validator_failure(tmp_path: Path) -> None:
    renderer = tmp_path / "render.sh"
    renderer.write_text("#!/bin/sh\nprintf 'apiVersion: v1\\nkind: ConfigMap\\n'\n")
    renderer.chmod(0o755)
    result = subprocess.run(
        ["make", "k8s-validate", f"KUSTOMIZE={renderer}", "KUBECONFORM=false"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode != 0, result.stdout + result.stderr
