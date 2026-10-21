"""`python -m ledger.worker`: importing builds nothing, and `main()` configures redacting logging
from the settings before the worker runs (D19)."""

import importlib
import logging
import os
import sys
from collections.abc import Iterator

import pytest
import structlog

import ledger.worker
from ledger.infrastructure.settings import Settings

# Only what this process gets in compose and k8s: no admin credentials, no privileged URLs.
ENV = {
    "LEDGER_ENVIRONMENT": "test",
    "LEDGER_AUTH_MODE": "dev",
    "LEDGER_DATABASE_URL": "postgresql+asyncpg://sb_app:x@h/ledger",
    "LEDGER_LOG_LEVEL": "DEBUG",
}
SB_OBS_HANDLER = "sb_obs.structlog"


def test_importing_the_worker_builds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """No LEDGER_* settings exist here, so importing would fail if it built the container."""
    for name in [n for n in os.environ if n.startswith("LEDGER_")]:
        monkeypatch.delenv(name)
    monkeypatch.delitem(sys.modules, "ledger.worker", raising=False)
    module = importlib.import_module("ledger.worker")
    assert callable(module.main)


@pytest.fixture
def clean_root_logger() -> Iterator[logging.Logger]:
    """Restore the root logger afterwards; start without sb_obs's handler."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    for h in [h for h in root.handlers if h.get_name() == SB_OBS_HANDLER]:
        root.removeHandler(h)
    try:
        yield root
    finally:
        root.handlers[:] = handlers
        root.setLevel(level)
        structlog.reset_defaults()


def test_main_configures_logging_before_the_worker_runs(
    monkeypatch: pytest.MonkeyPatch, clean_root_logger: logging.Logger
) -> None:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    seen: list[tuple[list[str], int]] = []

    async def recording_run(_: Settings) -> None:
        seen.append(
            ([h.get_name() or "" for h in clean_root_logger.handlers], clean_root_logger.level)
        )

    monkeypatch.setattr(ledger.worker, "run", recording_run)
    ledger.worker.main()
    assert len(seen) == 1
    handlers, level = seen[0]
    assert SB_OBS_HANDLER in handlers
    assert level == logging.DEBUG
