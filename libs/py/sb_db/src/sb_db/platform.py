"""Platform tables every service database carries: outbox, inbox, audit, idempotency.

`audit_events` and `idempotency_keys` are tenant-scoped (RLS). `outbox` and `inbox` are
infrastructure tables without RLS: the relay and consumers work across tenants.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Identity,
    Index,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB


@dataclass(frozen=True)
class PlatformTables:
    outbox: Table
    inbox: Table
    audit_events: Table
    idempotency_keys: Table


def install_platform_tables(metadata: MetaData) -> PlatformTables:
    tz = DateTime(timezone=True)
    outbox = Table(
        "outbox",
        metadata,
        Column("id", BigInteger, Identity(), primary_key=True),
        Column("event_id", Uuid(), nullable=False, unique=True),
        Column("tenant_id", Uuid(), nullable=False),
        Column("topic", Text, nullable=False),
        Column("key", Text, nullable=False),
        Column("payload", JSONB, nullable=False),
        Column("headers", JSONB, nullable=False),
        Column("occurred_at", tz, nullable=False),
        Column("published_at", tz, nullable=True, index=True),
    )
    inbox = Table(
        "inbox",
        metadata,
        Column("consumer", Text, nullable=False),
        Column("event_id", Uuid(), nullable=False),
        Column("processed_at", tz, nullable=False),
        PrimaryKeyConstraint("consumer", "event_id"),
    )
    audit_events = Table(
        "audit_events",
        metadata,
        Column("seq", BigInteger, Identity(), primary_key=True),
        Column("tenant_id", Uuid(), nullable=False, index=True),
        Column("actor", Text, nullable=False),
        Column("action", Text, nullable=False),
        Column("entity_type", Text, nullable=False),
        Column("entity_id", Text, nullable=False),
        Column("before", JSONB, nullable=True),
        Column("after", JSONB, nullable=True),
        Column("reason", Text, nullable=True),
        Column("request_id", Text, nullable=False),
        Column("trace_id", Text, nullable=True),
        Column("recorded_at", tz, nullable=False),
        Column("prev_hash", Text, nullable=True),
        Column("hash", Text, nullable=False),
        # One successor per link: a concurrent fork of a tenant's chain fails loudly. NULLS NOT
        # DISTINCT makes the genesis row (prev_hash NULL) unique per tenant too (Postgres 15+).
        Index(
            "uq_audit_events_tenant_prev_hash",
            "tenant_id",
            "prev_hash",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
    )
    idempotency_keys = Table(
        "idempotency_keys",
        metadata,
        Column("tenant_id", Uuid(), nullable=False),
        Column("key", Text, nullable=False),
        Column("request_hash", Text, nullable=False),
        Column("response", JSONB, nullable=False),
        Column("created_at", tz, nullable=False),
        PrimaryKeyConstraint("tenant_id", "key"),
    )
    return PlatformTables(outbox, inbox, audit_events, idempotency_keys)
