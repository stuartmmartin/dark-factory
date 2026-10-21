"""The event envelope on the wire: what happened, to whom, on whose behalf (A11, A13).

The payload is the `DomainEvent` as JSON. The metadata carries the request context across the
broker, so the consumer's unit of work runs as the tenant and actor that raised the event.

Unknown top-level fields are ignored (tolerant reader), so a newer producer can add one. The
flip side: a re-serialized envelope silently drops what this version does not know, so never
forward `to_bytes()` of a decoded envelope. Pass the original message bytes on instead.

Trust: Kafka is trusted, authenticated infrastructure (ACLs and mTLS in production), so the
tenant and actor in an envelope are trusted because of who could write it. `actor` and
`request_id` are still held to the same charset and length rules as HTTP (`sb_http.auth`), so a
malformed value is rejected at parse time, i.e. treated as poison, and never reaches a log line
or an audit row.
"""

from __future__ import annotations

import re
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    JsonValue,
    field_validator,
    model_validator,
)

from sb_kernel.context import RequestContext

# The same rules as sb_http.auth (_ACTOR_RE, _REQUEST_ID_RE); keep them in step.
_ACTOR_RE = re.compile(r"[A-Za-z0-9._:@-]{1,128}")
_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9._:-]{1,128}")


class EventEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True)  # unknown fields ignored: tolerant reader

    event_id: UUID
    event_type: str
    schema_version: int
    topic: str
    key: str
    occurred_at: AwareDatetime
    tenant_id: UUID
    actor: str
    request_id: str
    trace_id: str | None
    payload: dict[str, JsonValue]

    @field_validator("actor")
    @classmethod
    def _actor_is_safe(cls, value: str) -> str:
        if not _ACTOR_RE.fullmatch(value):
            raise ValueError("actor must be 1-128 chars of [A-Za-z0-9._:@-]")
        return value

    @field_validator("request_id")
    @classmethod
    def _request_id_is_safe(cls, value: str) -> str:
        if not _REQUEST_ID_RE.fullmatch(value):
            raise ValueError("request_id must be 1-128 chars of [A-Za-z0-9._:-]")
        return value

    @model_validator(mode="after")
    def _topic_follows_convention(self) -> EventEnvelope:
        expected = f"{self.event_type}.v{self.schema_version}"
        if self.topic != expected:
            raise ValueError(f"topic {self.topic!r} must be {expected!r}")
        return self

    def to_bytes(self) -> bytes:
        return self.model_dump_json().encode()

    @classmethod
    def from_bytes(cls, data: bytes) -> EventEnvelope:
        return cls.model_validate_json(data)

    def context(self) -> RequestContext:
        return RequestContext(
            tenant_id=self.tenant_id,
            actor=self.actor,
            request_id=self.request_id,
            trace_id=self.trace_id,
        )
