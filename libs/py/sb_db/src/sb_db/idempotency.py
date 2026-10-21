"""Idempotency-key storage (spec §10): same key + same request → the stored response.

`save` inserts with `ON CONFLICT DO NOTHING`. When the key already exists:
- with a different request hash, it raises `IdempotencyKeyReused` (422, as the IETF
  Idempotency-Key draft asks for a key reused with a different payload);
- with the same hash (a racing duplicate of the same request), it raises `Conflict` (409).
A racing insert waits for the first transaction, so the second save sees the committed row.
Either error leaves the use case's unit of work uncommitted, so it rolls back and a second
side effect can never be committed.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from sb_db.platform import PlatformTables
from sb_kernel.clock import Clock
from sb_kernel.context import RequestContext
from sb_kernel.errors import Conflict, IdempotencyKeyReused
from sb_kernel.uow import StoredResponse


class SqlIdempotencyStore:
    def __init__(
        self, session: AsyncSession, tables: PlatformTables, ctx: RequestContext, clock: Clock
    ) -> None:
        self._session, self._t, self._ctx, self._clock = (
            session,
            tables.idempotency_keys,
            ctx,
            clock,
        )

    async def get(self, key: str) -> StoredResponse | None:
        row = (
            await self._session.execute(
                select(self._t.c.request_hash, self._t.c.response).where(
                    self._t.c.tenant_id == self._ctx.tenant_id, self._t.c.key == key
                )
            )
        ).first()
        if row is None:
            return None
        return StoredResponse(cast(str, row.request_hash), cast(Mapping[str, object], row.response))

    async def save(self, key: str, request_hash: str, response: Mapping[str, object]) -> None:
        inserted = await self._session.execute(
            insert(self._t)
            .values(
                tenant_id=self._ctx.tenant_id,
                key=key,
                request_hash=request_hash,
                response=dict(response),
                created_at=self._clock.now(),
            )
            .on_conflict_do_nothing()
            .returning(self._t.c.key)
        )
        if inserted.first() is not None:
            return
        existing = await self.get(key)
        if existing is not None and existing.request_hash != request_hash:
            raise IdempotencyKeyReused("idempotency key already used for a different request")
        raise Conflict("idempotency key already in use")
