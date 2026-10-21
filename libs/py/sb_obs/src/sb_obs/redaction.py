"""Never log secrets or PII (C9): redact by key name, PII annotations, SecretStr and value shape."""

from __future__ import annotations

import dataclasses
import re
import typing
from collections import deque
from collections.abc import Mapping, MutableMapping
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Final, cast
from uuid import UUID

from pydantic import BaseModel, SecretBytes, SecretStr

REDACTED: Final = "[REDACTED]"
CYCLE: Final = "[CYCLE]"
TRUNCATED: Final = "[TRUNCATED]"
MAX_DEPTH: Final = 10
# Bare "pin" and "dob" are deliberately absent: they match too many innocent keys.
SENSITIVE_KEY_PARTS: Final = frozenset(
    {
        "password",
        "secret",
        "token",
        "api_key",
        "apikey",
        "authorization",
        "ssn",
        "tax_id",
        "account_number",
        "iban",
        "routing_number",
        "cookie",
        "credential",
        "private_key",
        "passwd",
        "pwd",
        "bearer",
        "card_number",
        "cvv",
        "session",
        "jwt",
        "refresh",
    }
)

_SECRET_VALUE_PATTERNS: Final = (
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@"),  # scheme://user:pass@
    re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]+"),  # JWT
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
)
_PASSTHROUGH: Final = (Decimal, UUID, datetime, date, time, timedelta, Enum)


class _PIIMarker:
    def __repr__(self) -> str:
        return "PII"


PII: Final = _PIIMarker()


def _sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def redact_string(text: str) -> str:
    """Replace secret-shaped substrings (bearer tokens, URL credentials, JWTs, API keys)."""
    for pattern in _SECRET_VALUE_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def _has_pii(annotation: object) -> bool:
    """True if PII appears anywhere in a type, through Annotated, unions and generic args."""
    if typing.get_origin(annotation) is typing.Annotated:
        base, *metadata = typing.get_args(annotation)
        return any(m is PII for m in metadata) or _has_pii(base)
    return any(_has_pii(arg) for arg in typing.get_args(annotation))


def redact_model(model: BaseModel) -> dict[str, object]:
    return _redact_model(model, 0, set())


def _redact_model(model: BaseModel, depth: int, seen: set[int]) -> dict[str, object]:
    out: dict[str, object] = {}
    for name, info in type(model).model_fields.items():
        if PII in info.metadata or _has_pii(info.annotation):
            out[name] = REDACTED
        else:
            out[name] = _redact(name, getattr(model, name), depth + 1, seen)
    return out


def redact_value(key: str, value: object) -> object:
    return _redact(key, value, 0, set())


def _redact(key: str, value: object, depth: int, seen: set[int]) -> object:  # noqa: PLR0911
    if isinstance(value, SecretStr | SecretBytes) or _sensitive_key(key):
        return REDACTED
    if value is None or isinstance(value, (bool, int, float, *_PASSTHROUGH)):
        return value
    if isinstance(value, str):
        return redact_string(value)
    if depth >= MAX_DEPTH:
        return TRUNCATED
    oid = id(value)
    if oid in seen:
        return CYCLE
    seen.add(oid)
    try:
        if isinstance(value, BaseModel):
            return _redact_model(value, depth, seen)
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return {
                f.name: _redact(f.name, getattr(value, f.name), depth + 1, seen)
                for f in dataclasses.fields(value)
            }
        if isinstance(value, Mapping):
            mapping = cast(Mapping[object, object], value)
            return {str(k): _redact(str(k), v, depth + 1, seen) for k, v in mapping.items()}
        if isinstance(value, list | tuple | set | frozenset | deque):
            items = cast(list[object], list(cast(Any, value)))
            return [_redact(key, v, depth + 1, seen) for v in items]
        return redact_string(repr(value))
    finally:
        seen.discard(oid)


def redact_processor(
    logger: object, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    del logger, method_name
    for key in list(event_dict):
        if key == "event":
            message = event_dict[key]
            event_dict[key] = redact_string(message) if isinstance(message, str) else message
        else:
            event_dict[key] = redact_value(key, event_dict[key])
    return event_dict
