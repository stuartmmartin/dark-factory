from decimal import Context, Decimal, localcontext

from hypothesis import given
from hypothesis import strategies as st

from ledger.application.policies.allocation import allocate
from sb_kernel.money import Money
from sb_testing.strategies import money

fractional = st.decimals(
    min_value=Decimal(0),
    max_value=Decimal(10) ** 12,
    places=18,
    allow_nan=False,
    allow_infinity=False,
)
long_weights = st.lists(fractional, min_size=1, max_size=10).filter(lambda ws: sum(ws) > 0)
weights = st.lists(
    st.integers(min_value=0, max_value=1000).map(Decimal), min_size=1, max_size=20
).filter(lambda ws: sum(ws) > 0)


@given(money("USD"), weights)
def test_parts_sum_exactly_to_total(total: Money, ws: list[Decimal]) -> None:
    parts = allocate(total, ws)
    acc = Money.zero("USD")
    for part in parts:
        acc = acc + part
    assert acc == total
    assert len(parts) == len(ws)


@given(money("USD"), weights)
def test_each_part_within_one_minor_unit_of_ideal(total: Money, ws: list[Decimal]) -> None:
    for part, w in zip(allocate(total, ws), ws, strict=True):
        ideal = total.amount * w / sum(ws)
        assert abs(part.amount - ideal) < Decimal("0.01")


@given(money("USD"), weights)
def test_deterministic_and_zero_weights_get_zero(total: Money, ws: list[Decimal]) -> None:
    first, second = allocate(total, ws), allocate(total, ws)
    assert first == second
    assert all(p.is_zero() for p, w in zip(first, ws, strict=True) if w == 0)


FULL = "99999999999999999999.99"
mixed = st.one_of(weights, long_weights)


@given(money("USD", "-" + FULL, FULL), mixed)
def test_full_range_parts_sum_exactly_and_stay_close(total: Money, ws: list[Decimal]) -> None:
    parts = allocate(total, ws)
    acc = Money.zero("USD")
    for part in parts:
        acc = acc + part
    assert acc == total
    weight_sum = sum(ws)
    for part, w in zip(parts, ws, strict=True):
        with localcontext(Context(prec=120)):
            ideal = total.amount * w / weight_sum
            assert abs(part.amount - ideal) < Decimal("0.01")


@given(money("USD"), long_weights)
def test_long_fractional_weights_sum_exactly(total: Money, ws: list[Decimal]) -> None:
    assert sum((p.amount for p in allocate(total, ws)), Decimal(0)) == total.amount


@given(money("JPY", "-99999999999999999999", "99999999999999999999"), mixed)
def test_zero_minor_unit_currency_sums_exactly(total: Money, ws: list[Decimal]) -> None:
    parts = allocate(total, ws)
    assert sum((p.amount for p in parts), Decimal(0)) == total.amount
    assert all(p.amount == p.amount.to_integral_value() for p in parts)


@given(money("KWD", "-99999999999999999999.999", "99999999999999999999.999"), mixed)
def test_three_minor_unit_currency_sums_exactly(total: Money, ws: list[Decimal]) -> None:
    parts = allocate(total, ws)
    assert sum((p.amount for p in parts), Decimal(0)) == total.amount
