"""Domain events published by the ledger."""

from __future__ import annotations

from typing import ClassVar
from uuid import UUID

from sb_kernel.events import DomainEvent


class AccountOpened(DomainEvent):
    """No account name in the payload: it can identify a family member and no consumer needs it."""

    event_type: ClassVar[str] = "ledger.account.opened"

    account_id: UUID
    currency: str

    def event_key(self) -> str:
        return str(self.account_id)
