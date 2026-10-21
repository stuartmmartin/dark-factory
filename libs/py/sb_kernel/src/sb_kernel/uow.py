"""Unit-of-work protocols that use cases depend on; sb_db implements them (A6, A11, A14)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import Protocol, Self

from sb_kernel.events import DomainEvent


class AuditLog(Protocol):
    def record(
        self,
        *,
        action: str,
        entity_type: str,
        entity_id: str,
        before: Mapping[str, object] | None,
        after: Mapping[str, object] | None,
        reason: str | None = None,
    ) -> None: ...


class Outbox(Protocol):
    def add(self, event: DomainEvent) -> None: ...


@dataclass(frozen=True)
class StoredResponse:
    request_hash: str
    response: Mapping[str, object]


class IdempotencyStore(Protocol):
    async def get(self, key: str) -> StoredResponse | None: ...
    async def save(self, key: str, request_hash: str, response: Mapping[str, object]) -> None: ...


class UnitOfWork(Protocol):
    audit: AuditLog
    outbox: Outbox
    idempotency: IdempotencyStore

    async def __aenter__(self) -> Self: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
