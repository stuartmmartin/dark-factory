from decimal import Context, Decimal, Inexact, localcontext

import pytest
from pydantic import ValidationError

from ledger.application.policies import allocation
from ledger.application.policies.allocation import AllocationInput, allocate, allocation_acceptor
from sb_kernel.errors import ValidationFailed
from sb_kernel.money import Money


def amounts(parts: list[Money]) -> list[str]:
    return [str(p.amount) for p in parts]


def test_equal_split_with_remainder_goes_to_first_parts() -> None:
    assert amounts(allocate(Money.of("100.00", "USD"), [Decimal(1)] * 3)) == [
        "33.34",
        "33.33",
        "33.33",
    ]


def test_weighted_split_uses_largest_remainder() -> None:
    assert amounts(allocate(Money.of("10.00", "USD"), [Decimal(1), Decimal(2)])) == ["3.33", "6.67"]


def test_single_weight_gets_everything() -> None:
    assert amounts(allocate(Money.of("10.00", "USD"), [Decimal(3)])) == ["10.00"]


def test_zero_weight_gets_zero() -> None:
    assert amounts(allocate(Money.of("1.00", "USD"), [Decimal(0), Decimal(1), Decimal(0)])) == [
        "0.00",
        "1.00",
        "0.00",
    ]


def test_negative_total_mirrors_positive() -> None:
    assert amounts(allocate(Money.of("-100.00", "USD"), [Decimal(1)] * 3)) == [
        "-33.34",
        "-33.33",
        "-33.33",
    ]


def test_zero_minor_unit_currency() -> None:
    assert amounts(allocate(Money.of("10", "JPY"), [Decimal(1)] * 3)) == ["4", "3", "3"]


@pytest.mark.parametrize("weights", [[], [Decimal(0)], [Decimal(-1), Decimal(2)]])
def test_invalid_weights_raise(weights: list[Decimal]) -> None:
    with pytest.raises(ValidationFailed, match="weights"):
        allocate(Money.of("1.00", "USD"), weights)


def test_total_with_excess_precision_raises() -> None:
    with pytest.raises(ValidationFailed, match="precision"):
        allocate(Money.of("1.005", "USD"), [Decimal(1)])


def test_acceptor_accepts_comma_separated_weights() -> None:
    out = allocation_acceptor(
        AllocationInput.model_validate({"total": "100.00", "currency": "usd", "weights": "1, 1, 2"})
    )
    assert out.model_dump(mode="json") == {"parts": ["25.00", "25.00", "50.00"], "currency": "USD"}


def test_acceptor_rejects_a_float_total() -> None:
    with pytest.raises(ValidationError, match="total"):  # D17
        AllocationInput.model_validate({"total": 100.5, "weights": "1"})


def test_acceptor_rejects_absurd_weight_exponent() -> None:
    inp = AllocationInput.model_validate({"total": "1.00", "weights": "1e999999,1"})
    with pytest.raises(ValidationFailed, match="weights"):
        allocation_acceptor(inp)


@pytest.mark.parametrize(
    "bad", [Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), Decimal("-Infinity")]
)
def test_non_finite_weights_raise(bad: Decimal) -> None:
    with pytest.raises(ValidationFailed, match="weights"):
        allocate(Money.of("1.00", "USD"), [Decimal(1), bad])


def test_overlong_weights_raise() -> None:
    with pytest.raises(ValidationFailed, match="weights"):
        allocate(Money.of("1.00", "USD"), [Decimal("1." + "1" * 40)])


def test_too_many_weights_rejected_by_input_model() -> None:
    with pytest.raises(ValidationError, match="weights"):
        AllocationInput.model_validate({"total": "1.00", "weights": ",".join(["1"] * 1001)})


def test_acceptor_accepts_typed_weights() -> None:
    inp = AllocationInput(total="1.00", weights=[Decimal(1), Decimal(3)])
    assert allocation_acceptor(inp).parts == ["0.25", "0.75"]


def test_arithmetic_failure_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    # Fault injection with a real decimal context: a platform precision regression must fail
    # closed, not return a rounded allocation. No mock of the policy or its arithmetic.
    context = Context(prec=3)
    context.traps[Inexact] = True
    monkeypatch.setattr(allocation, "_CTX", context)
    with pytest.raises(ValidationFailed, match="allocation arithmetic failed: Inexact"):
        allocate(Money.of("1.00", "USD"), [Decimal(1)] * 3)


def test_insufficient_precision_cannot_return_unreconciled_parts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(allocation, "_CTX", Context(prec=1))
    with pytest.raises(ValidationFailed, match="parts do not reconcile"):
        allocate(Money.of("100.00", "USD"), [Decimal(1)] * 3)


def test_result_does_not_depend_on_caller_decimal_context() -> None:
    expected = amounts(allocate(Money.of("100.00", "USD"), [Decimal(1)] * 3))
    hostile = Context(prec=3)
    hostile.traps[Inexact] = True
    with localcontext(hostile):
        assert amounts(allocate(Money.of("100.00", "USD"), [Decimal(1)] * 3)) == expected
