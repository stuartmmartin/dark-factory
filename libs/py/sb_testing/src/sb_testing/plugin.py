"""pytest plugin (auto-loaded via the pytest11 entry point) for every workspace member."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import cast

import pytest
import structlog

from sb_testing.clock import FakeClock
from sb_testing.kafka import kafka_bootstrap
from sb_testing.network import guard
from sb_testing.postgres import (
    postgres_app_url,
    postgres_container,
    postgres_migrator_url,
    postgres_url,
)

__all__ = [
    "fake_clock",
    "kafka_bootstrap",
    "postgres_app_url",
    "postgres_container",
    "postgres_migrator_url",
    "postgres_url",
]


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "allow_network: this test may open non-loopback connections (give a reason)"
    )


@pytest.fixture(autouse=True)
def _sb_forbid_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    node = cast(pytest.Item, request.node)  # pyright: ignore[reportUnknownMemberType] - untyped in pytest
    if node.get_closest_marker("allow_network") is None:
        guard(monkeypatch)


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock(datetime(2026, 1, 1, 9, tzinfo=UTC))


@pytest.fixture(autouse=True)
def _sb_reset_structlog() -> Iterator[None]:
    yield
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()
