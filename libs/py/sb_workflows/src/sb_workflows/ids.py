"""Deterministic workflow ids (A12): the same business key always maps to the same id.

Injectivity: `name` is a slug that cannot embed a UUID, and `key` cannot embed the tenant's
UUID, so `f"{name}-{tenant}-{key}"` cannot be re-split to give a different (name, tenant, key).
"""

import re
from uuid import UUID

_NAME = re.compile(r"[a-z][a-z0-9_]*(-[a-z0-9_]+)*")
_UUID_SHAPE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_MAX_KEY = 200


def workflow_id(name: str, tenant_id: UUID, key: str) -> str:
    """Return `<name>-<tenant_id>-<key>`, rejecting parts that could make ids collide."""
    if not isinstance(tenant_id, UUID):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError("workflow id tenant_id must be a UUID instance")
    if not _NAME.fullmatch(name) or _UUID_SHAPE.search(name):
        raise ValueError("workflow id name must be a lowercase slug without a UUID")
    if not 1 <= len(key) <= _MAX_KEY:
        raise ValueError(f"workflow id key must be 1-{_MAX_KEY} characters")
    if any(ch.isspace() or not ch.isprintable() for ch in key):
        raise ValueError("workflow id key must contain no whitespace or control characters")
    if str(tenant_id) in key.lower():
        raise ValueError("workflow id key must not contain the tenant id")
    return f"{name}-{tenant_id}-{key}"
