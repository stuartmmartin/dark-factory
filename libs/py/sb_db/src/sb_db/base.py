"""Declarative base factory (one metadata per service) and the tenant-scoped mixin."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import MetaData, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def new_metadata() -> MetaData:
    return MetaData(naming_convention=NAMING_CONVENTION)


def make_base() -> type[DeclarativeBase]:
    class Base(DeclarativeBase):
        metadata = new_metadata()

    return Base


class TenantScoped:
    """Mixin for tenant-owned tables; pair it with `enable_rls_sql` in the migration (A13)."""

    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
