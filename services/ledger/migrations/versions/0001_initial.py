"""Initial schema: accounts, the account-count projection and snapshots, plus platform tables.

Revision ID: 0001
Revises:
Create Date: 2026-09-29

RLS: the ledger's own tables get `enable_rls_sql`; the platform tables get their RLS and
append-only state only from `platform_table_ddl()` (D5). Grants follow D6: the database is owned
by sb_migrator and sb_app starts with only USAGE on `public`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from sb_db.rls import apply, enable_rls_sql, platform_table_ddl, platform_table_ddl_downgrade

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEDGER_TABLES = ("accounts", "account_counts", "account_count_snapshots")
PLATFORM_TABLES = ("outbox", "inbox", "audit_events", "idempotency_keys")
ALL_TABLES = (*LEDGER_TABLES, *PLATFORM_TABLES)

_TZ = sa.DateTime(timezone=True)


def _create_platform_tables() -> None:
    """Identical to `sb_db.platform.install_platform_tables` (the drift test checks it)."""
    op.create_table(
        "outbox",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("headers", postgresql.JSONB(), nullable=False),
        sa.Column("occurred_at", _TZ, nullable=False),
        sa.Column("published_at", _TZ, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_outbox"),
        sa.UniqueConstraint("event_id", name="uq_outbox_event_id"),
    )
    op.create_index("ix_outbox_published_at", "outbox", ["published_at"])
    op.create_table(
        "inbox",
        sa.Column("consumer", sa.Text(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("processed_at", _TZ, nullable=False),
        sa.PrimaryKeyConstraint("consumer", "event_id", name="pk_inbox"),
    )
    op.create_table(
        "audit_events",
        sa.Column("seq", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("before", postgresql.JSONB(), nullable=True),
        sa.Column("after", postgresql.JSONB(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("recorded_at", _TZ, nullable=False),
        sa.Column("prev_hash", sa.Text(), nullable=True),
        sa.Column("hash", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("seq", name="pk_audit_events"),
    )
    op.create_index("ix_audit_events_tenant_id", "audit_events", ["tenant_id"])
    op.create_index(
        "uq_audit_events_tenant_prev_hash",
        "audit_events",
        ["tenant_id", "prev_hash"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )
    op.create_table(
        "idempotency_keys",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("response", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", _TZ, nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "key", name="pk_idempotency_keys"),
    )


def _create_ledger_tables() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("opened_at", _TZ, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_accounts"),
    )
    op.create_index("ix_accounts_tenant_id", "accounts", ["tenant_id"])
    op.create_table(
        "account_counts",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("accounts", sa.Integer(), nullable=False),
        sa.Column("updated_at", _TZ, nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", name="pk_account_counts"),
    )
    op.create_table(
        "account_count_snapshots",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("accounts", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "as_of", name="pk_account_count_snapshots"),
    )


def upgrade() -> None:
    _create_platform_tables()
    _create_ledger_tables()
    apply(op, platform_table_ddl())  # audit_events/idempotency_keys: RLS + append-only (D5)
    for table in LEDGER_TABLES:  # never the platform tables: their policies exist already
        apply(op, enable_rls_sql(table))
    tables = ", ".join(ALL_TABLES)  # by name: ON ALL TABLES would include alembic_version
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tables} TO sb_app")
    op.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO sb_app")  # identity columns
    op.execute("GRANT USAGE ON SCHEMA public TO sb_readonly")
    op.execute(f"GRANT SELECT ON {tables} TO sb_readonly")


def downgrade() -> None:
    tables = ", ".join(ALL_TABLES)
    op.execute(f"REVOKE SELECT ON {tables} FROM sb_readonly")  # noqa: S608 - fixed names
    op.execute("REVOKE USAGE ON SCHEMA public FROM sb_readonly")
    op.execute("REVOKE USAGE ON ALL SEQUENCES IN SCHEMA public FROM sb_app")
    op.execute(f"REVOKE SELECT, INSERT, UPDATE, DELETE ON {tables} FROM sb_app")
    apply(op, platform_table_ddl_downgrade())  # while the platform tables still exist
    for table in reversed(LEDGER_TABLES):  # their policies go with them
        op.drop_table(table)
    for table in reversed(PLATFORM_TABLES):
        op.drop_table(table)
