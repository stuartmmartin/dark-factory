"""Wire form of money amounts (C3, D17): a decimal string, never a float or Decimal field.

The pattern is the NUMERIC(38,18) shape (at most 20 integer digits, 18 places).
`Money.of(value, currency)` still validates the value itself.
"""

from typing import Annotated

from pydantic import StringConstraints

from sb_kernel.money import Money

DecimalStr = Annotated[str, StringConstraints(pattern=r"^-?[0-9]{1,20}(\.[0-9]{1,18})?$")]


def to_decimal_str(money: Money) -> str:
    """The amount as a `DecimalStr` with exactly the currency's minor units, never rounded.

    Storage-scale zeros (`NUMERIC(38,18)` returns `100.000000000000000000`) are trimmed as text;
    any significant digit beyond the minor units is kept.
    """
    whole, _, fraction = f"{money.amount:f}".partition(".")
    fraction = fraction.rstrip("0").ljust(money.currency.minor_units, "0")
    return f"{whole}.{fraction}" if fraction else whole
