"""images.yml and deploy.yml: a service whose name contains `_` builds and deploys.

Naming convention: the Python package, the service directory and the compose prefix keep `_`
(`demo_svc`); the image, the k8s directory and every Kubernetes resource name use the
hyphenated form (`demo-svc`, the normalized distribution name sb-graph prints as `name`).
The deploy steps' shell is run for real (bash, no network) with the step's own env contract.
"""

import os
import subprocess
from pathlib import Path
from typing import cast

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO / ".github" / "workflows"
SHA = "0" * 40

Mapping = dict[str, object]


def _workflow(name: str) -> Mapping:
    return cast(Mapping, yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8")))


def _step(workflow: Mapping, job: str, name: str) -> Mapping:
    jobs = cast(dict[str, Mapping], workflow["jobs"])
    steps = cast(list[Mapping], jobs[job]["steps"])
    return next(s for s in steps if s.get("name") == name or s.get("id") == name)


def test_images_build_from_the_member_path_with_the_import_name() -> None:
    build = cast(Mapping, _step(_workflow("images.yml"), "build", "build")["with"])
    assert build["file"] == "${{ matrix.path }}/Dockerfile"
    assert build["build-args"] == "SERVICE=${{ matrix.import_name }}"
    image = cast(Mapping, _step(_workflow("images.yml"), "build", "image")["env"])
    assert image["SERVICE"] == "${{ matrix.name }}"  # the image name: hyphenated


def _run_step(
    step: Mapping, tmp_path: Path, **env: str
) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    github_env = tmp_path / "github_env"
    github_env.touch()
    result = subprocess.run(
        ["bash", "-e", "-c", cast(str, step["run"])],
        cwd=tmp_path,
        env={"PATH": os.environ["PATH"], "GITHUB_ENV": str(github_env), **env},  # env may set PATH
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    exported = dict(
        line.split("=", 1) for line in github_env.read_text().splitlines() if "=" in line
    )
    return result, exported


def _validate(tmp_path: Path, service: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    step = _step(_workflow("deploy.yml"), "deploy", "Validate inputs")
    return _run_step(
        step, tmp_path, REF="refs/heads/main", SERVICE=service, ENVIRONMENT="dev", SHA=SHA
    )


@pytest.mark.parametrize("service", ["demo_svc", "demo-svc"])
def test_deploy_maps_a_service_name_to_its_hyphenated_k8s_name(
    tmp_path: Path, service: str
) -> None:
    result, exported = _validate(tmp_path, service)
    assert result.returncode == 0, result.stdout + result.stderr
    assert exported["APP"] == "demo-svc"


@pytest.mark.parametrize("service", ["Demo", "demo svc", "demo;id", "-demo", "demo/../x", ""])
def test_deploy_refuses_an_invalid_service_name(tmp_path: Path, service: str) -> None:
    result, exported = _validate(tmp_path, service)
    assert result.returncode != 0
    assert "APP" not in exported


def test_deploy_resolves_the_hyphenated_overlay_and_image(tmp_path: Path) -> None:
    overlay = tmp_path / "deploy/k8s/demo-svc/overlays/dev"
    overlay.mkdir(parents=True)
    (overlay / "kustomization.yaml").touch()
    step = _step(_workflow("deploy.yml"), "deploy", "Resolve overlay")
    result, exported = _run_step(step, tmp_path, APP="demo-svc", ENVIRONMENT="dev", OWNER="Acme")
    assert result.returncode == 0, result.stdout + result.stderr
    assert exported["OVERLAY"] == "deploy/k8s/demo-svc/overlays/dev"
    assert exported["IMAGE"] == "ghcr.io/acme/dark-factory-demo-svc"


def test_deploy_uses_the_hyphenated_name_after_validation() -> None:
    """Only `Validate inputs` reads the raw input; every later step uses $APP."""
    jobs = cast(dict[str, Mapping], _workflow("deploy.yml")["jobs"])
    steps = cast(list[Mapping], jobs["deploy"]["steps"])
    later = [s for s in steps if "run" in s and s.get("name") != "Validate inputs"]
    assert later
    assert [s["name"] for s in later if "$SERVICE" in cast(str, s["run"])] == []
    assert [s["name"] for s in later if "${SERVICE}" in cast(str, s["run"])] == []


IMAGE = "ghcr.io/acme/dark-factory-demo-svc"
DIGEST = "sha256:" + "a" * 64


def _render(tmp_path: Path, *images: str) -> subprocess.CompletedProcess[str]:
    """Run the Render step with a stand-in kustomize that renders `images`."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    manifest = "".join(f"- name: c{i}\n  image: {image}\n" for i, image in enumerate(images))
    kustomize = bin_dir / "kustomize"
    kustomize.write_text(f"#!/bin/sh\ncat <<'YAML'\n{manifest}YAML\n")
    kustomize.chmod(0o755)
    step = _step(_workflow("deploy.yml"), "deploy", "Render")
    result, _ = _run_step(
        step,
        tmp_path,
        PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        OVERLAY="deploy/k8s/demo-svc/overlays/dev",
        IMAGE=IMAGE,
        DIGEST=DIGEST,
        RUNNER_TEMP=str(tmp_path),
    )
    return result


def test_render_accepts_only_the_verified_digest(tmp_path: Path) -> None:
    assert _render(tmp_path, f"{IMAGE}@{DIGEST}", f"{IMAGE}@{DIGEST}").returncode == 0


@pytest.mark.parametrize(
    "stray",
    [
        "ghcr.io/stuartmmartin/dark-factory-demo-svc:latest-dev",  # `set image` did not match
        f"{IMAGE}@sha256:{'b' * 64}",
    ],
)
def test_render_refuses_any_other_image(tmp_path: Path, stray: str) -> None:
    result = _render(tmp_path, f"{IMAGE}@{DIGEST}", stray)
    assert result.returncode != 0
    assert "rendered images differ" in result.stdout


def test_provenance_pins_the_signer_identity_and_hosted_runners() -> None:
    script = cast(str, _step(_workflow("deploy.yml"), "deploy", "Verify provenance")["run"])
    identity = (
        '--cert-identity "https://github.com/${GITHUB_REPOSITORY}'
        '/.github/workflows/images.yml@refs/heads/main"'
    )
    assert identity in script
    assert "--deny-self-hosted-runners" in script
    assert "--source-ref refs/heads/main" in script
    assert '--source-digest "$SHA"' in script
    assert "--signer-workflow" not in script  # gh refuses it together with --cert-identity
