import json
from pathlib import Path, PurePosixPath

import pytest

from sb_agentkit.hookio import HookInput


class FakeBaseRef:
    """Test double for BaseRef: a fixed set of paths that 'exist on origin/main'."""

    def __init__(self, existing: set[str] | None = None) -> None:
        self.existing = {PurePosixPath(p) for p in existing or set()}

    def exists_on_base(self, rel: PurePosixPath, root: Path) -> bool:
        del root
        return rel in self.existing


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def edit_input(repo: Path):
    def _make(file_path: str, tool: str = "Edit") -> HookInput:
        raw = json.dumps(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": tool,
                "tool_input": {"file_path": file_path},
                "cwd": str(repo),
            }
        )
        parsed = HookInput.parse(raw, default_cwd=repo)
        assert parsed is not None
        return parsed

    return _make


@pytest.fixture
def base():
    return FakeBaseRef
