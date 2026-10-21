"""Domain events: frozen pydantic models; topic = <event_type>.v<schema_version> (A11)."""

from __future__ import annotations

from abc import abstractmethod
from typing import ClassVar

from pydantic import BaseModel, ConfigDict


class DomainEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_type: ClassVar[str]
    schema_version: ClassVar[int] = 1

    @classmethod
    def topic(cls) -> str:
        return f"{cls.event_type}.v{cls.schema_version}"

    @abstractmethod
    def event_key(self) -> str:
        """Partition key: events with the same key are ordered."""
