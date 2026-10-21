"""Hypothesis strategies for domain types (T6)."""

from __future__ import annotations

from decimal import Decimal

from hypothesis import strategies as st

from sb_kernel.money import Currency, Money


def money(
    currency: str = "USD", min_value: str = "-1000000", max_value: str = "1000000"
) -> st.SearchStrategy[Money]:
    cur = Currency.of(currency)
    return st.decimals(
        min_value=Decimal(min_value),
        max_value=Decimal(max_value),
        places=cur.minor_units,
        allow_nan=False,
        allow_infinity=False,
    ).map(lambda amount: Money.of(amount, cur))
