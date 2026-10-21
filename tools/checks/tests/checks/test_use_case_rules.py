from sb_checks.checks.use_case_rules import UseCaseRulesCheck

UC = "services/ledger/src/ledger/application/use_cases/open_account.py"
TEST = "services/ledger/tests/unit/use_cases/test_open_account.py"

DOCSTRING = '''\
"""Open an account for a legal entity.

Business rules:
    R1: The account code is unique per tenant.
    R2: The currency is a supported ISO 4217 code.
"""
'''


def test_every_rule_has_a_test(run_check) -> None:
    tests = "def test_R1_duplicate_code_conflicts(): ...\n\ndef test_R2_rejects_xxx(): ...\n"
    assert run_check(UseCaseRulesCheck(), UC, DOCSTRING, {TEST: tests}) == []


def test_rule_tests_inside_classes_count(run_check) -> None:
    tests = "class TestOpen:\n    def test_R1_a(self): ...\n    def test_R2_b(self): ...\n"
    assert run_check(UseCaseRulesCheck(), UC, DOCSTRING, {TEST: tests}) == []


def test_missing_docstring_rules_is_a_violation(run_check) -> None:
    [v] = run_check(UseCaseRulesCheck(), UC, '"""Open an account."""\n', {TEST: ""})
    assert "R1:" in v.message


def test_missing_test_file_is_a_violation(run_check) -> None:
    [v] = run_check(UseCaseRulesCheck(), UC, DOCSTRING)
    assert TEST in v.message


def test_untested_rule_is_a_violation(run_check) -> None:
    [v] = run_check(UseCaseRulesCheck(), UC, DOCSTRING, {TEST: "def test_R1_a(): ...\n"})
    assert "R2" in v.message
    assert str(v.path) == UC


def test_test_for_unknown_rule_is_reported_against_the_test_file(run_check) -> None:
    tests = "def test_R1_a(): ...\ndef test_R2_b(): ...\ndef test_R9_orphan(): ...\n"
    [v] = run_check(UseCaseRulesCheck(), UC, DOCSTRING, {TEST: tests})
    assert str(v.path) == TEST
    assert "R9" in v.message


def test_package_init_is_ignored(run_check) -> None:
    rel = "services/ledger/src/ledger/application/use_cases/__init__.py"
    assert run_check(UseCaseRulesCheck(), rel, "") == []


def test_broken_test_file_is_a_syntax_error_violation_not_a_crash(run_check) -> None:
    [v] = run_check(UseCaseRulesCheck(), UC, DOCSTRING, {TEST: "def test_R1_a(:\n    ...\n"})
    assert v.check_id == "syntax-error"
    assert str(v.path) == TEST
