import pytest

from sb_kernel.errors import (
    Conflict,
    CurrencyMismatch,
    DomainError,
    Forbidden,
    IdempotencyKeyReused,
    NotFound,
    ValidationFailed,
)


@pytest.mark.parametrize(
    ("cls", "code"),
    [
        (NotFound, "not_found"),
        (Conflict, "conflict"),
        (ValidationFailed, "validation_failed"),
        (Forbidden, "forbidden"),
        (CurrencyMismatch, "currency_mismatch"),
        (IdempotencyKeyReused, "idempotency_key_reused"),
    ],
)
def test_codes_and_hierarchy(cls: type[DomainError], code: str) -> None:
    err = cls("boom")
    assert isinstance(err, DomainError)
    assert (err.code, str(err)) == (code, "boom")


def test_idempotency_key_reused_is_a_validation_failure() -> None:
    assert issubclass(IdempotencyKeyReused, ValidationFailed)
