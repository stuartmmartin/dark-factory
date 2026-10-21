"""Alembic environment for the ledger: the shared `sb_db` runner over the ledger metadata."""

from alembic import context

from ledger.infrastructure.models import Base
from ledger.infrastructure.settings import load_settings
from ledger.migrate import migrator_url
from sb_db.alembic_env import run_migrations

url = context.config.attributes.get("url") or migrator_url(load_settings())
run_migrations(url, Base.metadata)
