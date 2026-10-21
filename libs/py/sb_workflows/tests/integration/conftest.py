"""Run this directory's async tests on the session loop (same pattern as sb_db)."""

import sys
from pathlib import Path

import pytest
from pytest_asyncio import is_async_test

_HERE = Path(__file__).parent
# The workflow sandbox re-imports workflow modules by name; pytest importlib mode does not put
# this directory on sys.path, so sample_workflows would not be importable there.
sys.path.insert(0, str(_HERE))


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    session_loop = pytest.mark.asyncio(loop_scope="session")
    for item in items:
        if is_async_test(item) and _HERE in item.path.parents:
            item.add_marker(session_loop, append=False)
