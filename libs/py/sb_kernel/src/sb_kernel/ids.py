"""Identifiers. UUIDs everywhere; NewTypes make tenant ids hard to confuse with other ids."""

from typing import NewType
from uuid import UUID, uuid4

TenantId = NewType("TenantId", UUID)


def new_id() -> UUID:
    return uuid4()
