"""Tamper-evident audit log (A14): SHA-256 hash chain per tenant, written in the use case's UoW.

Each row's hash is `sha256(prev_hash + canonical_json(fields))` over `_HASHED_FIELDS`, so any
edit, reorder or deletion inside a tenant's chain is detected by `verify_chain`. `before` and
`after` are canonicalized when recorded (Decimal/UUID/datetime become strings; floats are
refused, C3), so later mutation of the caller's dict changes nothing and the stored JSONB is
exactly what was hashed. A unique index on (tenant_id, prev_hash) makes a forked chain fail.

Out of scope: deleting the chain's *tail* (the newest rows) leaves a valid shorter chain.
Detecting that needs an external anchor (e.g. periodically publishing the head hash).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from sb_db.lifecycle import FINISHED
from sb_db.platform import PlatformTables
from sb_db.rls import TENANT_SETTING
from sb_kernel.clock import Clock
from sb_kernel.context import RequestContext

_HASHED_FIELDS = (
    "tenant_id",
    "actor",
    "action",
    "entity_type",
    "entity_id",
    "before",
    "after",
    "reason",
    "request_id",
    "trace_id",
    "recorded_at",
)


def _reject_floats(value: object) -> None:
    if isinstance(value, float):
        raise TypeError("float is not allowed in audit data; use Decimal (C3)")
    if isinstance(value, Mapping):
        for item in cast(Mapping[object, object], value).values():
            _reject_floats(item)
    elif isinstance(value, list | tuple):
        for item in cast(list[object] | tuple[object, ...], value):
            _reject_floats(item)


def _default(value: object) -> str:
    if isinstance(value, Decimal | UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise TypeError("naive datetime is not allowed in audit data (C4)")
        return value.astimezone(UTC).isoformat()
    raise TypeError(f"not JSON-serializable: {type(value).__name__}")


def canonical_json(value: object) -> str:
    """Deterministic JSON: sorted keys, no whitespace; Decimal/UUID as str, datetimes in UTC."""
    _reject_floats(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=_default)


def chain_hash(prev_hash: str | None, row: Mapping[str, object]) -> str:
    return hashlib.sha256(((prev_hash or "") + canonical_json(dict(row))).encode()).hexdigest()


def _as_stored(payload: Mapping[str, object] | None) -> dict[str, Any] | None:
    """The JSON-native form Postgres will hand back, so insert- and verify-time hashes agree."""
    if payload is None:
        return None
    return cast(dict[str, Any], json.loads(canonical_json(payload)))


@dataclass(frozen=True)
class _Pending:
    action: str
    entity_type: str
    entity_id: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    reason: str | None


class SqlAuditLog:
    """Buffers records during the use case; the UoW flushes them just before commit."""

    def __init__(self, tables: PlatformTables, ctx: RequestContext, clock: Clock) -> None:
        self._tables, self._ctx, self._clock = tables, ctx, clock
        self._pending: list[_Pending] = []
        self._closed = False

    def close(self) -> None:
        """Drop anything buffered; later records raise (the unit of work is finished)."""
        self._pending.clear()
        self._closed = True

    def record(
        self,
        *,
        action: str,
        entity_type: str,
        entity_id: str,
        before: Mapping[str, object] | None,
        after: Mapping[str, object] | None,
        reason: str | None = None,
    ) -> None:
        if self._closed:
            raise RuntimeError(FINISHED)
        self._pending.append(
            _Pending(action, entity_type, entity_id, _as_stored(before), _as_stored(after), reason)
        )

    async def flush(self, session: AsyncSession) -> None:
        if not self._pending:
            return
        audit = self._tables.audit_events
        # Serialize chain appends per tenant until this transaction ends (READ COMMITTED:
        # the SELECT below then sees the previous writer's committed tail).
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext('sb_audit'), hashtext(:tenant))"),
            {"tenant": str(self._ctx.tenant_id)},
        )
        prev: str | None = (
            await session.execute(
                select(audit.c.hash)
                .where(audit.c.tenant_id == self._ctx.tenant_id)
                .order_by(audit.c.seq.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        for item in self._pending:
            row: dict[str, Any] = {
                "tenant_id": self._ctx.tenant_id,
                "actor": self._ctx.actor,
                "action": item.action,
                "entity_type": item.entity_type,
                "entity_id": item.entity_id,
                "before": item.before,
                "after": item.after,
                "reason": item.reason,
                "request_id": self._ctx.request_id,
                "trace_id": self._ctx.trace_id,
                "recorded_at": self._clock.now(),
            }
            digest = chain_hash(prev, {k: row[k] for k in _HASHED_FIELDS})
            await session.execute(insert(audit).values(**row, prev_hash=prev, hash=digest))
            prev = digest
        self._pending.clear()


async def verify_chain(session: AsyncSession, tenant_id: UUID, tables: PlatformTables) -> bool:
    """Recompute every hash for the tenant in seq order; False on the first mismatch.

    The session must be scoped to that tenant: under RLS another tenant's chain would read as
    empty and "verify", so a mismatch is refused rather than reported as True.
    """
    scoped = (
        await session.execute(text("SELECT current_setting(:k, true)"), {"k": TENANT_SETTING})
    ).scalar_one_or_none()
    if scoped != str(tenant_id):
        raise ValueError(f"session is scoped to tenant {scoped!r}, not {tenant_id}")
    audit = tables.audit_events
    rows = (
        await session.execute(
            select(audit).where(audit.c.tenant_id == tenant_id).order_by(audit.c.seq)
        )
    ).mappings()
    prev: str | None = None
    for row in rows:
        body = {k: row[k] for k in _HASHED_FIELDS}
        if row["prev_hash"] != prev or row["hash"] != chain_hash(prev, body):
            return False
        prev = row["hash"]
    return True
