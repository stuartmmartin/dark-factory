"""Root pytest configuration shared by every workspace member.

Tier markers are derived from the test path, so nobody has to remember to add them:
any test under a directory named ``integration`` gets ``@pytest.mark.integration``.
"""

import os

import pytest
from hypothesis import settings

# ci: reproducible and quick. nightly: a much deeper search (HYPOTHESIS_PROFILE=nightly).
settings.register_profile("ci", derandomize=True, max_examples=100)
settings.register_profile("nightly", max_examples=2000, print_blob=True)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    del config
    for item in items:
        if "integration" in item.path.parts:
            item.add_marker(pytest.mark.integration)
