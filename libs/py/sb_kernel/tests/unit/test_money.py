from decimal import ROUND_FLOOR, Decimal

import pytest

from sb_kernel.errors import CurrencyMismatch, ValidationFailed
from sb_kernel.money import Currency, Money


def test_of_accepts_str_int_decimal_and_keeps_exact_amount() -> None:
    assert Money.of("10.005", "usd").amount == Decimal("10.005")
    assert Money.of(3, "JPY").amount == Decimal(3)
    assert Money.of(Decimal("1.10"), Currency.of("EUR")).currency.code == "EUR"


@pytest.mark.parametrize("bad", [1.5, "1,000.00", "abc", "NaN", "Infinity", ""])
def test_of_rejects_float_and_malformed_amounts(bad: object) -> None:
    with pytest.raises(ValidationFailed):
        Money.of(bad, "USD")  # type: ignore[arg-type]  # deliberately wrong type


def test_unknown_currency_is_rejected() -> None:
    with pytest.raises(ValidationFailed, match="XYZ"):
        Currency.of("XYZ")


def test_minor_units_follow_iso_4217() -> None:
    assert (
        Currency.of("USD").minor_units,
        Currency.of("JPY").minor_units,
        Currency.of("KWD").minor_units,
    ) == (2, 0, 3)


def test_arithmetic_same_currency() -> None:
    a, b = Money.of("10.25", "USD"), Money.of("0.75", "USD")
    assert (a + b, a - b, -a, a * 2) == (
        Money.of("11.00", "USD"),
        Money.of("9.50", "USD"),
        Money.of("-10.25", "USD"),
        Money.of("20.50", "USD"),
    )


@pytest.mark.parametrize("op", ["add", "sub", "lt"])
def test_mixed_currency_raises(op: str) -> None:
    usd, eur = Money.of(1, "USD"), Money.of(1, "EUR")
    with pytest.raises(CurrencyMismatch):
        {"add": lambda: usd + eur, "sub": lambda: usd - eur, "lt": lambda: usd < eur}[op]()


def test_multiply_by_float_is_rejected() -> None:
    with pytest.raises(ValidationFailed):
        Money.of(1, "USD") * 1.5  # type: ignore[operator]  # deliberately wrong type


def test_quantized_uses_bankers_rounding_by_default() -> None:
    assert Money.of("0.125", "USD").quantized().amount == Decimal("0.12")
    assert Money.of("0.135", "USD").quantized().amount == Decimal("0.14")
    assert Money.of("2.5", "JPY").quantized().amount == Decimal(2)


def test_minor_units_requires_exact_precision() -> None:
    assert Money.of("12.34", "USD").minor_units() == 1234
    with pytest.raises(ValidationFailed):
        Money.of("12.345", "USD").minor_units()


def test_str_and_zero() -> None:
    assert str(Money.of("12.3", "USD")) == "USD 12.30"
    assert Money.zero("USD").is_zero()


def test_hash_ignores_trailing_zeros() -> None:
    assert hash(Money.of("1.10", "USD")) == hash(Money.of("1.1", "USD"))


def test_eq_across_currencies_is_false_and_non_money_is_not_equal() -> None:
    assert Money.of(1, "USD") != Money.of(1, "EUR")
    assert Money.of(1, "USD") != 1


def test_bool_is_rejected_in_of_and_mul() -> None:
    with pytest.raises(ValidationFailed):
        Money.of(True, "USD")  # type: ignore[arg-type]  # deliberately wrong type
    with pytest.raises(ValidationFailed):
        _ = Money.of(1, "USD") * True


@pytest.mark.parametrize(
    "bad", [Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), Decimal("-Infinity")]
)
def test_non_finite_decimal_objects_are_rejected(bad: Decimal) -> None:
    with pytest.raises(ValidationFailed):
        Money.of(bad, "USD")
    with pytest.raises(ValidationFailed):
        _ = Money.of(1, "USD") * bad


def test_raw_constructor_validates_amount() -> None:
    usd = Currency.of("USD")
    with pytest.raises(ValidationFailed):
        Money(1.5, usd)  # type: ignore[arg-type]  # deliberately wrong type
    with pytest.raises(ValidationFailed):
        Money(True, usd)  # type: ignore[arg-type]  # deliberately wrong type
    with pytest.raises(ValidationFailed):
        Money(Decimal("NaN"), usd)


@pytest.mark.parametrize(
    "bad", ["1_000", " 1", "1 ", "1e3", "1E3", "1.", ".5", "+", "--1", "1,000.00"]
)
def test_strict_string_parsing(bad: str) -> None:
    with pytest.raises(ValidationFailed):
        Money.of(bad, "USD")


def test_signed_strings_and_negative_zero() -> None:
    assert Money.of("+1.5", "USD").amount == Decimal("1.5")
    zero = Money.of("-0", "USD")
    assert str(zero.amount) == "0"
    assert not zero.amount.is_signed()
    assert not (Money.zero("USD") * -1).amount.is_signed()


def test_overflow_raises_validation_failed() -> None:
    big = Money.of("9" * 20, "USD")
    with pytest.raises(ValidationFailed):
        _ = big * Decimal("1e999999")
    with pytest.raises(ValidationFailed):
        _ = big + big  # 21 integer digits: outside NUMERIC(38,18)


@pytest.mark.parametrize(
    "bad",
    [
        Decimal("1E+999990"),
        Decimal("1E-999990"),
        Decimal("1" * 39),  # 39 significant digits
        Decimal("1" * 21),  # 21 integer digits
        Decimal("0." + "0" * 18 + "1"),  # 19 decimal places
        Decimal("1E+20"),  # adjusted exponent 20: 21 integer digits
    ],
)
def test_amounts_outside_numeric_38_18_are_rejected(bad: Decimal) -> None:
    with pytest.raises(ValidationFailed, match="NUMERIC"):
        Money.of(bad, "USD")
    with pytest.raises(ValidationFailed, match="NUMERIC"):
        Money(bad, Currency.of("USD"))


def test_numeric_38_18_boundary_values_are_accepted() -> None:
    widest = "9" * 20 + "." + "9" * 18  # 20 integer digits + 18 decimals = 38 digits
    assert Money.of(widest, "USD").amount == Decimal(widest)
    assert Money.of("-" + widest, "USD").amount == Decimal("-" + widest)
    assert (-Money.of(widest, "USD")).amount == Decimal("-" + widest)  # negation is exact
    assert Money.of(Decimal("1E+19"), "USD").amount == Decimal("1E+19")
    assert Money.of("0." + "0" * 17 + "1", "USD").amount == Decimal("1E-18")


def test_error_messages_truncate_echoed_input() -> None:
    with pytest.raises(ValidationFailed) as bad_str:
        Money.of("x" * 10_000, "USD")
    assert len(bad_str.value.message) < 120
    with pytest.raises(ValidationFailed) as too_big:
        Money.of(Decimal("7" * 5_000), "USD")
    assert len(too_big.value.message) < 160


def test_multiplication_that_would_round_at_prec_60_is_rejected_not_rounded() -> None:
    # The arithmetic context has prec=60 and traps Inexact: a product needing more than 60
    # significant digits raises instead of silently rounding.
    amount = Money.of("1" * 20 + "." + "1" * 18, "USD")  # 38 digits
    factor = Decimal("1." + "1" * 29)  # 30 digits -> the exact product has 67
    with pytest.raises(ValidationFailed, match="Inexact"):
        _ = amount * factor


def test_sum_needs_a_money_start_value() -> None:
    items = [Money.of("1.10", "USD"), Money.of("2.20", "USD")]
    assert sum(items, Money.zero("USD")) == Money.of("3.30", "USD")


def test_non_money_operands_return_not_implemented() -> None:
    m = Money.of(1, "USD")
    assert m.__add__(1) is NotImplemented  # type: ignore[arg-type]
    assert m.__sub__(1) is NotImplemented  # type: ignore[arg-type]
    assert m.__lt__(1) is NotImplemented  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        m + 1  # type: ignore[operator]


@pytest.mark.parametrize("op", ["le", "gt", "ge"])
def test_other_comparisons_mixed_currency_raise(op: str) -> None:
    usd, eur = Money.of(1, "USD"), Money.of(1, "EUR")
    fns = {"le": lambda: usd <= eur, "gt": lambda: usd > eur, "ge": lambda: usd >= eur}
    with pytest.raises(CurrencyMismatch):
        fns[op]()


@pytest.mark.parametrize(("left", "right"), [("1", "1"), ("1", "2"), ("2", "1")])
def test_comparison_boundaries(left: str, right: str) -> None:
    a, b = Money.of(left, "USD"), Money.of(right, "USD")
    assert (a <= b) == (Decimal(left) <= Decimal(right))
    assert (a > b) == (Decimal(left) > Decimal(right))
    assert (a >= b) == (Decimal(left) >= Decimal(right))


def test_remaining_comparisons_refuse_non_money_operands() -> None:
    m = Money.of(1, "USD")
    assert m.__le__(1) is NotImplemented  # type: ignore[arg-type] - test runtime operand rejection
    assert m.__gt__(1) is NotImplemented  # type: ignore[arg-type] - test runtime operand rejection
    assert m.__ge__(1) is NotImplemented  # type: ignore[arg-type] - test runtime operand rejection


def test_negative_rounding_and_negative_str() -> None:
    assert Money.of("-0.125", "USD").quantized().amount == Decimal("-0.12")
    assert Money.of("-0.135", "USD").quantized().amount == Decimal("-0.14")
    assert Money.of("-0.121", "USD").quantized(ROUND_FLOOR).amount == Decimal("-0.13")
    assert str(Money.of("-12.3", "USD")) == "USD -12.30"


def test_quantized_rejects_unknown_rounding() -> None:
    with pytest.raises(ValidationFailed):
        Money.of(1, "USD").quantized("nope")


def test_str_never_hides_precision() -> None:
    assert str(Money.of("12.345", "USD")) == "USD 12.345"
    assert str(Money.of("12.3", "USD")) == "USD 12.30"
    assert str(Money.of("5", "JPY")) == "JPY 5"
    assert str(Money.of("1.2345", "KWD")) == "KWD 1.2345"


def test_minor_units_error_shows_exact_amount() -> None:
    with pytest.raises(ValidationFailed, match=r"USD 12\.345"):
        Money.of("12.345", "USD").minor_units()
