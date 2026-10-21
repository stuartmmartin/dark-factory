"""Account entity and its invariants."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sb_kernel.errors import ValidationFailed
from sb_kernel.money import Currency

MAX_NAME = 200


@dataclass(frozen=True, slots=True)
class Account:
    id: UUID
    tenant_id: UUID
    name: str
    currency: Currency
    opened_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):  # pyright: ignore[reportUnnecessaryIsInstance]  # runtime guard
            raise ValidationFailed("name must be a string")
        # Non-blank, and the stored length (padding included) is what the column holds.
        if not self.name.strip() or len(self.name) > MAX_NAME:
            raise ValidationFailed(f"name must be 1-{MAX_NAME} characters")
        if self.opened_at.tzinfo is None or self.opened_at.utcoffset() is None:
            raise ValidationFailed("opened_at must be timezone-aware")
