"""Journal: double-entry entries and their lines (expand only).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-19

Both tables are tenant-scoped (RLS) and append-only: a correction is a new, reversing entry, so
sb_app gets SELECT and INSERT only. The composite foreign keys reference `(id, tenant_id)`, so a
line can never point at another tenant's entry or account (foreign-key checks bypass RLS).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from sb_db.rls import append_only_sql, apply, enable_rls_sql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JOURNAL_TABLES = ("journal_entries", "journal_lines")


def upgrade() -> None:
    op.create_unique_constraint("uq_accounts_id", "accounts", ["id", "tenant_id"])
    op.create_table(
        "journal_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_journal_entries"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_journal_entries_id"),
    )
    op.create_index("ix_journal_entries_tenant_id", "journal_entries", ["tenant_id"])
    op.create_table(
        "journal_lines",
        sa.Column("entry_id", sa.Uuid(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(38, 18), nullable=False),
        sa.PrimaryKeyConstraint("entry_id", "line_no", name="pk_journal_lines"),
        sa.ForeignKeyConstraint(
            ["entry_id", "tenant_id"],
            ["journal_entries.id", "journal_entries.tenant_id"],
            name="fk_journal_lines_entry_id_journal_entries",
        ),
        sa.ForeignKeyConstraint(
            ["account_id", "tenant_id"],
            ["accounts.id", "accounts.tenant_id"],
            name="fk_journal_lines_account_id_accounts",
        ),
        sa.CheckConstraint("side IN ('debit', 'credit')", name="ck_journal_lines_side"),
        sa.CheckConstraint("amount > 0", name="ck_journal_lines_amount_positive"),
    )
    op.create_index("ix_journal_lines_tenant_id", "journal_lines", ["tenant_id"])
    op.create_index("ix_journal_lines_account_id", "journal_lines", ["account_id"])
    for table in JOURNAL_TABLES:
        apply(op, enable_rls_sql(table))
        apply(op, append_only_sql(table))
    op.execute("GRANT SELECT, INSERT ON journal_entries, journal_lines TO sb_app")
    op.execute("GRANT SELECT ON journal_entries, journal_lines TO sb_readonly")


def downgrade() -> None:
    op.execute("REVOKE SELECT ON journal_entries, journal_lines FROM sb_readonly")
    op.execute("REVOKE SELECT, INSERT ON journal_entries, journal_lines FROM sb_app")
    op.drop_table("journal_lines")  # its policy and triggers go with it
    op.drop_table("journal_entries")
    op.execute("DROP FUNCTION IF EXISTS journal_lines_append_only()")
    op.execute("DROP FUNCTION IF EXISTS journal_entries_append_only()")
    op.drop_constraint("uq_accounts_id", "accounts", type_="unique")
