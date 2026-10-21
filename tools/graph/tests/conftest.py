import subprocess
import textwrap
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

AddMember = Callable[..., Path]
GitRunner = Callable[..., None]


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.uv.workspace]\nmembers = ["libs/py/*", "services/*", "tools/*"]\n'
    )
    return tmp_path


@pytest.fixture
def add_member(workspace: Path) -> AddMember:
    def _add(
        rel: str,
        name: str,
        deps: Sequence[str] = (),
        files: dict[str, str] | None = None,
        extra_toml: str = "",
    ) -> Path:
        directory = workspace / rel
        directory.mkdir(parents=True)
        deps_toml = ", ".join(f'"{dep}"' for dep in deps)
        (directory / "pyproject.toml").write_text(
            f'[project]\nname = "{name}"\nversion = "0.1.0"\n'
            f"dependencies = [{deps_toml}]\n{extra_toml}"
        )
        for file_rel, source in (files or {}).items():
            file = directory / file_rel
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(textwrap.dedent(source))
        return directory

    return _add


@pytest.fixture
def git() -> GitRunner:
    def _run(root: Path, *args: str) -> None:
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=t@example.com",
                "-c",
                "user.name=t",
                "-c",
                "commit.gpgsign=false",
                "-c",
                "tag.gpgsign=false",
                *args,
            ],
            cwd=root,
            check=True,
            capture_output=True,
        )

    return _run
