"""Offline (`--sql`) smoke test: a real Alembic script dir whose env.py calls run_migrations."""

import io
from pathlib import Path

from alembic import command
from alembic.config import Config

_ENV = """
from sqlalchemy import MetaData

from sb_db.alembic_env import run_migrations

run_migrations("postgresql+asyncpg://nobody@127.0.0.1:1/none", MetaData())
"""

_REVISION = """
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("smoke_widgets", sa.Column("id", sa.Integer, primary_key=True))


def downgrade() -> None:
    op.drop_table("smoke_widgets")
"""


def test_offline_upgrade_renders_the_revision_ddl(tmp_path: Path) -> None:
    script_dir = tmp_path / "migrations"
    (script_dir / "versions").mkdir(parents=True)
    (script_dir / "env.py").write_text(_ENV)
    (script_dir / "versions" / "0001_smoke.py").write_text(_REVISION)
    buffer = io.StringIO()
    cfg = Config(output_buffer=buffer)
    cfg.set_main_option("script_location", str(script_dir))

    command.upgrade(cfg, "head", sql=True)

    sql = buffer.getvalue()
    assert "CREATE TABLE smoke_widgets" in sql
    assert "INSERT INTO alembic_version (version_num) VALUES ('0001')" in sql
