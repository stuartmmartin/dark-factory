from datetime import UTC, datetime
from uuid import UUID

import pytest

from ledger.domain.accounts import Account
from sb_kernel.errors import ValidationFailed
from sb_kernel.money import Currency

OPENED = datetime(2026, 3, 1, 12, tzinfo=UTC)


def make(**over: object) -> Account:
    data: dict[str, object] = {
        "id": UUID(int=1),
        "tenant_id": UUID(int=9),
        "name": "Operating cash",
        "currency": Currency.of("USD"),
        "opened_at": OPENED,
    }
    data.update(over)
    return Account(**data)  # type: ignore[arg-type]


def test_valid_account() -> None:
    assert make().currency.code == "USD"


@pytest.mark.parametrize(
    "name",
    ["", "   ", "x" * 201, " " * 150 + "x" + " " * 149],
    ids=["empty", "blank", "201", "padded-300"],
)
def test_invalid_names_are_rejected(name: str) -> None:
    with pytest.raises(ValidationFailed, match="name"):
        make(name=name)


def test_naive_opened_at_is_rejected() -> None:
    with pytest.raises(ValidationFailed, match="timezone"):
        make(opened_at=datetime(2026, 3, 1))  # noqa: DTZ001


def test_non_string_name_is_rejected() -> None:
    with pytest.raises(ValidationFailed, match="name"):
        make(name=123)
