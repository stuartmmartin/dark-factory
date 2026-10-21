"""ORM tables of the ledger database: the ledger's own tables plus the platform tables.

Every ledger table is tenant-scoped; the initial migration puts RLS on each (A13, D5).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from sb_db.base import TenantScoped, make_base
from sb_db.platform import install_platform_tables

Base = make_base()
platform = install_platform_tables(Base.metadata)


class AccountRow(TenantScoped, Base):
    __tablename__ = "accounts"
    # The target of the journal lines' composite foreign key (a line stays in its tenant).
    __table_args__ = (UniqueConstraint("id", "tenant_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JournalEntryRow(TenantScoped, Base):
    """Append-only (migration 0002): a correction is a new, reversing entry."""

    __tablename__ = "journal_entries"
    __table_args__ = (UniqueConstraint("id", "tenant_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JournalLineRow(TenantScoped, Base):
    """Append-only. Composite foreign keys keep a line in its entry's and account's tenant."""

    __tablename__ = "journal_lines"
    __table_args__ = (
        ForeignKeyConstraint(
            ["entry_id", "tenant_id"], ["journal_entries.id", "journal_entries.tenant_id"]
        ),
        ForeignKeyConstraint(["account_id", "tenant_id"], ["accounts.id", "accounts.tenant_id"]),
        CheckConstraint("side IN ('debit', 'credit')", name="side"),
        CheckConstraint("amount > 0", name="amount_positive"),
        Index(None, "account_id"),
    )

    entry_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    line_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    side: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)


class AccountCountRow(Base):
    """The per-tenant projection maintained by the AccountOpened consumer."""

    __tablename__ = "account_counts"

    tenant_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    accounts: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AccountCountSnapshotRow(Base):
    __tablename__ = "account_count_snapshots"

    tenant_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    as_of: Mapped[date] = mapped_column(Date, primary_key=True)
    accounts: Mapped[int] = mapped_column(Integer, nullable=False)
