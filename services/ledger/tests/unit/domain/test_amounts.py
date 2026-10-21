from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from ledger.domain.amounts import DecimalStr, to_decimal_str
from sb_kernel.money import Money


class Wire(BaseModel):
    amount: DecimalStr


@pytest.mark.parametrize("value", ["100.00", "-0.5", "1.005", "0", "9" * 20, "0." + "1" * 18])
def test_valid_amounts(value: str) -> None:
    assert Wire.model_validate({"amount": value}).amount == value


@pytest.mark.parametrize(
    "value", ["1e3", "1,000.00", "+1", ".", "1.", "", "9" * 21, "0." + "1" * 19, " 1"]
)
def test_invalid_amounts(value: str) -> None:
    with pytest.raises(ValidationError):
        Wire.model_validate({"amount": value})


@pytest.mark.parametrize("value", [1.5, 1, Decimal("1.5")])
def test_non_string_inputs_are_rejected(value: object) -> None:
    with pytest.raises(ValidationError):
        Wire.model_validate({"amount": value})


@pytest.mark.parametrize(
    ("amount", "currency", "wire"),
    [
        ("100", "USD", "100.00"),
        ("-25.5", "USD", "-25.50"),
        ("7", "JPY", "7"),
        ("1.5", "KWD", "1.500"),
    ],
)
def test_to_decimal_str_pads_to_the_currency_minor_units(
    amount: str, currency: str, wire: str
) -> None:
    assert to_decimal_str(Money.of(amount, currency)) == wire


def test_to_decimal_str_never_rounds() -> None:
    assert to_decimal_str(Money.of("1.005", "USD")) == "1.005"


@pytest.mark.parametrize(
    ("amount", "wire"),
    [
        ("100.000000000000000000", "100.00"),
        ("-0.500000", "-0.50"),
        ("1.2300000001", "1.2300000001"),
    ],
)
def test_to_decimal_str_trims_storage_scale_zeros(amount: str, wire: str) -> None:
    assert to_decimal_str(Money.of(amount, "USD")) == wire
