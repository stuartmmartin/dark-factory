"""Typed domain/application errors. Mapped to HTTP exactly once, in sb_http (C8)."""

from __future__ import annotations

from typing import ClassVar


class DomainError(Exception):
    code: ClassVar[str] = "domain_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFound(DomainError):  # noqa: N818 - names fixed by the kernel interface
    code: ClassVar[str] = "not_found"


class Conflict(DomainError):  # noqa: N818 - names fixed by the kernel interface
    code: ClassVar[str] = "conflict"


class ValidationFailed(DomainError):  # noqa: N818 - names fixed by the kernel interface
    code: ClassVar[str] = "validation_failed"


class Forbidden(DomainError):  # noqa: N818 - names fixed by the kernel interface
    code: ClassVar[str] = "forbidden"


class CurrencyMismatch(ValidationFailed):
    code: ClassVar[str] = "currency_mismatch"


class IdempotencyKeyReused(ValidationFailed):
    """An Idempotency-Key already used for a different request (422, IETF idempotency draft)."""

    code: ClassVar[str] = "idempotency_key_reused"
