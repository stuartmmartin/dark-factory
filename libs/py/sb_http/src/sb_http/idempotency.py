"""Idempotency-Key header dependency and request fingerprint."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Collection, Sequence
from typing import Any, cast

from fastapi import Header
from pydantic import BaseModel, TypeAdapter

from sb_kernel.errors import ValidationFailed

__all__ = ["IDEMPOTENCY_HEADER", "idempotency_key", "request_hash"]

IDEMPOTENCY_HEADER = "Idempotency-Key"
_KEY_RE = re.compile(r"[A-Za-z0-9._:-]{1,200}")


def idempotency_key(key: str | None = Header(None, alias=IDEMPOTENCY_HEADER)) -> str | None:
    if key is None:
        return None
    if not _KEY_RE.fullmatch(key):
        raise ValidationFailed(f"{IDEMPOTENCY_HEADER} must be 1-200 chars of [A-Za-z0-9._:-]")
    return key


_ANY: TypeAdapter[Any] = TypeAdapter(Any)


def _jsonable(value: Any) -> Any:
    return _ANY.dump_python(value, mode="json")


def _normalise(value: Any) -> Any:
    """Make unordered containers deterministic: sets become sorted lists."""
    if isinstance(value, dict):
        d = cast(dict[Any, Any], value)
        return {k: _normalise(v) for k, v in d.items()}
    if isinstance(value, list | tuple):
        return [_normalise(v) for v in cast(Sequence[Any], value)]
    if isinstance(value, set | frozenset):
        items = [_normalise(v) for v in cast(Collection[Any], value)]
        return sorted(items, key=lambda v: json.dumps(_jsonable(v), sort_keys=True))
    return value


def request_hash(model: BaseModel) -> str:
    """SHA-256 of a canonical JSON form of the model.

    Keys are sorted and set/frozenset fields are sorted, so field and set order do not
    matter. Decimals hash by their string form, so `1.1` and `1.10` are different requests.
    """
    canonical = json.dumps(
        _jsonable(_normalise(model.model_dump(mode="python"))),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
