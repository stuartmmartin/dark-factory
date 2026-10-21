"""Migrations round-trip (upgrade → downgrade → upgrade), have a single head, and match the models.

Sync tests (D7): Alembic's env.py runs asyncio.run itself.
"""

import asyncio

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine
from structlog.testing import capture_logs

from ledger.infrastructure.models import Base
from ledger.infrastructure.settings import Settings
from ledger.migrate import alembic_config, migrate
from sb_db.engine import COMMAND_TIMEOUT_SECONDS, CONNECT_TIMEOUT_SECONDS


async def _diff(url: str) -> list[object]:
    engine = create_async_engine(
        url,
        poolclass=pool.NullPool,
        connect_args={
            "timeout": CONNECT_TIMEOUT_SECONDS,
            "command_timeout": COMMAND_TIMEOUT_SECONDS,
        },
    )
    try:
        async with engine.connect() as conn:
            return await conn.run_sync(
                lambda sync: compare_metadata(MigrationContext.configure(sync), Base.metadata)
            )
    finally:
        await engine.dispose()


def test_single_head(ledger_migrator_url: str) -> None:
    assert len(ScriptDirectory.from_config(alembic_config(ledger_migrator_url)).get_heads()) == 1


def test_round_trip_and_no_drift(ledger_db: str, ledger_migrator_url: str) -> None:
    config = alembic_config(ledger_migrator_url)
    command.downgrade(config, "base")  # also proves platform_table_ddl_downgrade (D5)
    command.upgrade(config, "head")
    assert asyncio.run(_diff(ledger_migrator_url)) == []


def test_migrate_upgrades_and_logs_the_head_revision(
    ledger_db: str, ledger_settings: Settings, ledger_migrator_url: str
) -> None:
    head = ScriptDirectory.from_config(alembic_config(ledger_migrator_url)).get_current_head()
    settings = ledger_settings.model_copy(update={"database_name": "ledger_test"})
    with capture_logs() as logs:
        assert migrate(settings) == head
    assert [e for e in logs if e["event"] == "ledger.migrated"] == [
        {
            "event": "ledger.migrated",
            "log_level": "info",
            "revision": head,
            "database": "ledger_test",
        }
    ]
