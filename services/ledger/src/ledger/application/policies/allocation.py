"""Split an amount by weights with no lost minor units (largest remainder method, C3).

Pure (A5): no I/O, no clock. Exposed to humans as the "Allocation" SQLAdmin acceptor.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import (
    ROUND_FLOOR,
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
)

from pydantic import BaseModel, Field, field_validator

from ledger.domain.amounts import DecimalStr
from sb_kernel.errors import ValidationFailed
from sb_kernel.money import Currency, Money

VERSION = "1"
# Explicit context: the result never depends on the caller's decimal context. The headroom is
# for long weights: minor * w / sum(w) must keep the integer part exact and enough fraction
# digits to rank remainders, or the parts would not sum to the total.
_PRECISION = 80
_CTX = Context(
    prec=_PRECISION,
    rounding=ROUND_HALF_EVEN,
    traps=[InvalidOperation, Overflow, DivisionByZero],
)
MAX_WEIGHT_DIGITS = 38
MAX_WEIGHT_ADJUSTED = 40  # adjusted exponent of a weight must lie within +-this
MAX_WEIGHTS = 1000


def _check_weights(weights: Sequence[Decimal]) -> None:
    if not weights:
        raise ValidationFailed("weights must not be empty")
    for w in weights:
        if not w.is_finite():
            raise ValidationFailed("weights must be finite numbers")
        if len(w.as_tuple().digits) > MAX_WEIGHT_DIGITS or (
            w != 0 and abs(w.adjusted()) > MAX_WEIGHT_ADJUSTED
        ):
            raise ValidationFailed("weights are too large, too small or too precise")
        if w < 0:
            raise ValidationFailed("weights must not be negative")


def allocate(total: Money, weights: Sequence[Decimal]) -> list[Money]:
    _check_weights(weights)
    try:
        return _allocate(total, weights)
    except ArithmeticError as exc:
        raise ValidationFailed(f"allocation arithmetic failed: {type(exc).__name__}") from exc


def _allocate(total: Money, weights: Sequence[Decimal]) -> list[Money]:
    weight_sum = Decimal(0)
    for w in weights:
        weight_sum = _CTX.add(weight_sum, w)
    if weight_sum <= 0:
        raise ValidationFailed("weights must sum to more than zero")
    if total.amount < 0:
        return [-part for part in _allocate(-total, weights)]
    minor = total.minor_units()  # raises ValidationFailed on excess precision
    ideal = [_CTX.divide(_CTX.multiply(Decimal(minor), w), weight_sum) for w in weights]
    floors = [int(x.to_integral_value(rounding=ROUND_FLOOR, context=_CTX)) for x in ideal]
    leftover = minor - sum(floors)
    if not 0 <= leftover <= len(weights):
        raise ValidationFailed("allocation arithmetic failed: parts do not reconcile")
    order = sorted(
        range(len(weights)),
        key=lambda i: (_CTX.subtract(Decimal(floors[i]), ideal[i]), i),
    )
    for i in order[:leftover]:
        floors[i] += 1
    exponent = Decimal(-total.currency.minor_units)
    return [Money.of(_CTX.scaleb(Decimal(units), exponent), total.currency) for units in floors]


def _split_decimals(value: object) -> object:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return value


class AllocationInput(BaseModel):
    total: DecimalStr = Field(description="Amount to split, e.g. 100.00")
    currency: str = Field(default="USD", description="ISO 4217 code")
    weights: list[Decimal] = Field(
        min_length=1, max_length=MAX_WEIGHTS, description="Comma-separated weights, e.g. 1,1,2"
    )

    _weights = field_validator("weights", mode="before")(_split_decimals)


class AllocationOutput(BaseModel):
    parts: list[str]
    currency: str


def allocation_acceptor(inp: AllocationInput) -> AllocationOutput:
    currency = Currency.of(inp.currency)
    parts = allocate(Money.of(inp.total, currency), inp.weights)
    return AllocationOutput(parts=[str(p.amount) for p in parts], currency=currency.code)
