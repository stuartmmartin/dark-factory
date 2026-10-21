import pytest

from sb_checks.checks.no_float import NoFloatCheck

DOMAIN = "services/ledger/src/ledger/domain/money.py"
APPLICATION = "services/ledger/src/ledger/application/policies/allocation.py"
KERNEL = "libs/py/sb_kernel/src/sb_kernel/money.py"
INFRA = "services/ledger/src/ledger/infrastructure/db/models.py"


def test_flags_float_call_in_domain(run_check) -> None:
    [v] = run_check(NoFloatCheck(), DOMAIN, "x = float('1.5')\n")
    assert v.check_id == "no-float"
    assert v.line == 1


def test_flags_float_annotation_in_application(run_check) -> None:
    violations = run_check(NoFloatCheck(), APPLICATION, "def f(a: float) -> None: ...\n")
    assert len(violations) == 1


def test_flags_float_literal_in_kernel(run_check) -> None:
    [v] = run_check(NoFloatCheck(), KERNEL, "RATE = 0.05\n")
    assert "0.05" in v.message


@pytest.mark.parametrize("rel", [INFRA, "services/ledger/tests/unit/test_x.py"])
def test_ignores_other_layers_and_tests(run_check, rel: str) -> None:
    assert run_check(NoFloatCheck(), rel, "x = float(1)\n") == []


def test_decimal_is_fine(run_check) -> None:
    source = "from decimal import Decimal\nRATE = Decimal('0.05')\n"
    assert run_check(NoFloatCheck(), DOMAIN, source) == []


class TestDocumentedBlindSpots:
    def test_string_annotations_are_not_inspected(self, run_check) -> None:
        assert run_check(NoFloatCheck(), DOMAIN, "def f(a: 'float') -> None: ...\n") == []
