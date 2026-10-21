from hypothesis import given

from sb_kernel.money import Money
from sb_testing.strategies import money


@given(money("JPY"))
def test_generated_money_is_quantized(value: Money) -> None:
    assert value.currency.code == "JPY"
    assert value.quantized() == value
