import importlib
import json
import logging
import sys
from collections.abc import Iterator

import pytest
import structlog
from fastapi import FastAPI

from ledger.main import create

ENV = {
    "LEDGER_ENVIRONMENT": "test",
    "LEDGER_AUTH_MODE": "dev",
    "LEDGER_DATABASE_URL": "postgresql+asyncpg://sb_app:x@h/ledger",
    "LEDGER_MIGRATOR_URL": "postgresql+asyncpg://sb_migrator:x@h/ledger",
    "LEDGER_ADMIN_DATABASE_URL": "postgresql+asyncpg://sb_admin:x@h/postgres",
    "LEDGER_ADMIN_USERNAME": "admin",
    "LEDGER_ADMIN_PASSWORD": "pw",
    "LEDGER_ADMIN_SECRET_KEY": "k" * 32,
    "LEDGER_LOG_LEVEL": "DEBUG",
}
SB_OBS_HANDLER = "sb_obs.structlog"


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
        structlog.reset_defaults()  # drop the config bound to capsys's stream


def test_importing_main_builds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """No settings exist here, so importing would fail if it built the app (D19)."""
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delitem(sys.modules, "ledger.main", raising=False)
    module = importlib.import_module("ledger.main")
    assert callable(module.create)
    assert callable(module.main)


async def test_create_configures_redacting_logging(
    monkeypatch: pytest.MonkeyPatch,
    clean_root_logger: logging.Logger,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The factory configures logging itself: under `--reload`, uvicorn's child process imports
    and calls `create()` fresh and never runs `main()` (D19)."""
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    app: FastAPI = create()
    try:
        assert SB_OBS_HANDLER in [h.get_name() for h in clean_root_logger.handlers]
        assert clean_root_logger.level == logging.DEBUG  # from the same settings
        logging.getLogger("uvicorn.error").warning("Bearer abc.def")
        record = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert record["logger"] == "uvicorn.error"
        assert "abc.def" not in record["event"]
    finally:
        await app.state.container.engine.dispose()
