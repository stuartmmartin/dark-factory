from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from sb_kernel.money import Money

amounts = st.decimals(
    min_value=Decimal("-1e12"),
    max_value=Decimal("1e12"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


@given(amounts, amounts)
def test_addition_commutes_and_subtraction_inverts(a: Decimal, b: Decimal) -> None:
    x, y = Money.of(a, "USD"), Money.of(b, "USD")
    assert x + y == y + x
    assert (x + y) - y == x


@given(amounts)
def test_quantized_is_idempotent_and_exact_in_minor_units(a: Decimal) -> None:
    q = Money.of(a, "USD").quantized()
    assert q.quantized() == q
    assert Money.of(Decimal(q.minor_units()) / 100, "USD") == q


amounts6 = st.decimals(
    min_value=Decimal("-1e12"),
    max_value=Decimal("1e12"),
    places=6,
    allow_nan=False,
    allow_infinity=False,
)


@given(amounts6, st.sampled_from(["USD", "JPY", "KWD"]))
def test_quantized_invariants_any_currency(a: Decimal, cur: str) -> None:
    m = Money.of(a, cur)
    q = m.quantized()
    assert q.quantized() == q
    assert Money.of(Decimal(q.minor_units()).scaleb(-q.currency.minor_units), cur) == q
    assert abs(q.amount - m.amount) <= Decimal(1).scaleb(-q.currency.minor_units) / 2


@given(amounts6, amounts6)
def test_hash_consistent_with_eq_and_str_roundtrips(a: Decimal, b: Decimal) -> None:
    x = Money.of(a, "USD")
    assert hash(x) == hash(Money.of(str(a), "USD"))
    assert Money.of(str(x).split(" ")[1], "USD") == x
    assert (x < Money.of(b, "USD")) == (a < b)
