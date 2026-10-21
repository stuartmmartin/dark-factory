"""Money: exact Decimal amounts in an ISO 4217 currency. Float is never accepted (C3).

Bounds: every amount fits Postgres `NUMERIC(38,18)`, the column type money is stored in: at most
38 significant digits, at most 18 decimal places and at most 20 integer digits. Anything else is
`ValidationFailed` at construction, so a hostile `Decimal("1E+999999")` is rejected before any
arithmetic touches it.

Arithmetic runs in a 60-digit context that traps `Inexact`: an operation whose exact result
needs more than 60 significant digits (only a multiplication by a long factor can) raises
`ValidationFailed` ("Inexact") instead of rounding silently. A result outside NUMERIC(38,18) is
rejected by the bounds above. Rounding happens only in `quantized()`.

Summing: `sum()` starts at the int 0, which Money does not add to. Pass a start value:
`sum(items, Money.zero(currency))`.
"""

from __future__ import annotations

import re
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import (
    ROUND_05UP,
    ROUND_CEILING,
    ROUND_DOWN,
    ROUND_FLOOR,
    ROUND_HALF_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    ROUND_UP,
    Context,
    Decimal,
    Inexact,
    InvalidOperation,
    Overflow,
    localcontext,
)
from types import MappingProxyType
from typing import cast

from sb_kernel.errors import CurrencyMismatch, ValidationFailed

CURRENCY_MINOR_UNITS: Mapping[str, int] = MappingProxyType(
    {
        "USD": 2,
        "EUR": 2,
        "GBP": 2,
        "CHF": 2,
        "CAD": 2,
        "AUD": 2,
        "NZD": 2,
        "SEK": 2,
        "NOK": 2,
        "DKK": 2,
        "HKD": 2,
        "SGD": 2,
        "CNY": 2,
        "INR": 2,
        "MXN": 2,
        "BRL": 2,
        "ZAR": 2,
        "ILS": 2,
        "AED": 2,
        "JPY": 0,
        "KRW": 0,
        "KWD": 3,
        "BHD": 3,
        "OMR": 3,
    }
)


@dataclass(frozen=True, slots=True)
class Currency:
    code: str
    minor_units: int

    @classmethod
    def of(cls, code: str) -> Currency:
        normalized = code.strip().upper()
        if normalized not in CURRENCY_MINOR_UNITS:
            raise ValidationFailed(f"unsupported currency {normalized!r}")
        return cls(normalized, CURRENCY_MINOR_UNITS[normalized])


_AMOUNT_RE = re.compile(r"[+-]?[0-9]+(\.[0-9]+)?", re.ASCII)
_ROUNDINGS = frozenset(
    {
        ROUND_05UP,
        ROUND_CEILING,
        ROUND_DOWN,
        ROUND_FLOOR,
        ROUND_HALF_DOWN,
        ROUND_HALF_EVEN,
        ROUND_HALF_UP,
        ROUND_UP,
    }
)
# Inexact is trapped too: an operation that would silently lose digits is an error, not a rounding.
_ARITHMETIC = Context(prec=60, traps=[InvalidOperation, Overflow, Inexact])
# NUMERIC(38,18): the storage bound every amount must fit.
MAX_DIGITS = 38
MAX_PLACES = 18
MAX_INTEGER_DIGITS = MAX_DIGITS - MAX_PLACES
_ECHO_LIMIT = 64  # never echo more than this much caller input in an error message
# quantize rounds by design, so Inexact is allowed there (and only there).
_QUANTIZE = Context(prec=60, traps=[InvalidOperation, Overflow])


@contextmanager
def _exact(context: Context = _ARITHMETIC) -> Generator[None]:
    """Run decimal arithmetic in a bounded, trapping context; failures become ValidationFailed."""
    try:
        with localcontext(context):
            yield
    except ArithmeticError as exc:
        raise ValidationFailed(f"money arithmetic failed: {type(exc).__name__}") from exc


def _echo(value: object) -> str:
    return repr(value)[:_ECHO_LIMIT]


def _check_bounds(amount: Decimal) -> None:
    """Reject amounts that do not fit NUMERIC(38,18), without expanding the exponent."""
    parts = amount.as_tuple()
    digits, exponent = parts.digits, parts.exponent
    places = -exponent if isinstance(exponent, int) and exponent < 0 else 0
    # adjusted() is the exponent of the leading digit: 19 means 20 integer digits
    if (
        len(digits) > MAX_DIGITS
        or places > MAX_PLACES
        or (amount != 0 and amount.adjusted() >= MAX_INTEGER_DIGITS)
    ):
        raise ValidationFailed(
            f"amount {_echo(amount)} does not fit NUMERIC({MAX_DIGITS},{MAX_PLACES})"
        )


def _to_decimal(amount: Decimal | int | str) -> Decimal:
    if isinstance(amount, bool) or not isinstance(amount, Decimal | int | str):  # pyright: ignore[reportUnnecessaryIsInstance]  # runtime guard
        raise ValidationFailed(f"amount must be Decimal, int or str, not {type(amount).__name__}")
    if isinstance(amount, str):
        if _AMOUNT_RE.fullmatch(amount) is None:
            raise ValidationFailed(f"invalid amount {_echo(amount)}")
        return Decimal(amount)
    return Decimal(amount)


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: Currency

    def __post_init__(self) -> None:
        amount = cast("object", self.amount)  # validate what callers actually passed
        if isinstance(amount, bool) or not isinstance(amount, Decimal):
            raise ValidationFailed(f"amount must be a Decimal, not {type(amount).__name__}")
        if not amount.is_finite():
            raise ValidationFailed(f"amount must be finite, got {_echo(amount)}")
        _check_bounds(amount)
        if amount.is_signed() and amount == 0:
            object.__setattr__(self, "amount", amount.copy_abs())  # normalise -0 to 0

    @classmethod
    def of(cls, amount: Decimal | int | str, currency: str | Currency) -> Money:
        cur = currency if isinstance(currency, Currency) else Currency.of(currency)
        return cls(_to_decimal(amount), cur)

    @classmethod
    def zero(cls, currency: str | Currency) -> Money:
        return cls.of(0, currency)

    def _same(self, other: Money) -> None:
        if other.currency != self.currency:
            raise CurrencyMismatch(f"{self.currency.code} vs {other.currency.code}")

    def __add__(self, other: Money) -> Money:
        if not isinstance(other, Money):  # pyright: ignore[reportUnnecessaryIsInstance]  # runtime guard
            return NotImplemented
        self._same(other)
        with _exact():
            return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        if not isinstance(other, Money):  # pyright: ignore[reportUnnecessaryIsInstance]  # runtime guard
            return NotImplemented
        self._same(other)
        with _exact():
            return Money(self.amount - other.amount, self.currency)

    def __neg__(self) -> Money:
        return Money(self.amount.copy_negate(), self.currency)  # exact: no context rounding

    def __mul__(self, factor: Decimal | int) -> Money:
        if isinstance(factor, bool) or not isinstance(factor, Decimal | int):  # pyright: ignore[reportUnnecessaryIsInstance]  # runtime guard
            raise ValidationFailed(
                f"Money can only be multiplied by Decimal or int, not {type(factor).__name__}"
            )
        if isinstance(factor, Decimal) and not factor.is_finite():
            raise ValidationFailed(f"factor must be finite, got {_echo(factor)}")
        with _exact():
            return Money(self.amount * factor, self.currency)

    def __lt__(self, other: Money) -> bool:
        if not isinstance(other, Money):  # pyright: ignore[reportUnnecessaryIsInstance]  # runtime guard
            return NotImplemented
        self._same(other)
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        if not isinstance(other, Money):  # pyright: ignore[reportUnnecessaryIsInstance]  # runtime guard
            return NotImplemented
        self._same(other)
        return self.amount <= other.amount

    def __gt__(self, other: Money) -> bool:
        if not isinstance(other, Money):  # pyright: ignore[reportUnnecessaryIsInstance]  # runtime guard
            return NotImplemented
        self._same(other)
        return self.amount > other.amount

    def __ge__(self, other: Money) -> bool:
        if not isinstance(other, Money):  # pyright: ignore[reportUnnecessaryIsInstance]  # runtime guard
            return NotImplemented
        self._same(other)
        return self.amount >= other.amount

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self.currency == other.currency and self.amount == other.amount

    def __hash__(self) -> int:
        return hash((self.amount, self.currency))

    def is_zero(self) -> bool:
        return self.amount == 0

    def quantized(self, rounding: str = ROUND_HALF_EVEN) -> Money:
        if rounding not in _ROUNDINGS:
            raise ValidationFailed(f"unknown rounding mode {rounding!r}")
        exponent = Decimal(1).scaleb(-self.currency.minor_units)
        with _exact(_QUANTIZE):
            return Money(self.amount.quantize(exponent, rounding=rounding), self.currency)

    def minor_units(self) -> int:
        with _exact():
            scaled = self.amount.scaleb(self.currency.minor_units)
            if scaled != scaled.to_integral_value():
                raise ValidationFailed(
                    f"{self} has more precision than {self.currency.code} allows"
                )
            return int(scaled)

    def __str__(self) -> str:
        """Exact amount: minor-unit format when it fits, every digit otherwise."""
        exponent = self.amount.as_tuple().exponent
        # exponent is a str only for NaN/Infinity, which construction rejects
        places = (
            self.currency.minor_units
            if not isinstance(exponent, int)
            else max(self.currency.minor_units, -exponent)
        )
        return f"{self.currency.code} {self.amount:.{places}f}"
