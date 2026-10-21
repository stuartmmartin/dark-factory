---
name: tdd
description: Test-driven development for dark_factory — use before writing ANY production code (feature, bug fix, refactor, use case, policy, adapter). Red-green-refactor with pasted evidence, R<n> rule tests, fakes not mocks.
---
# TDD in dark_factory (T1)

## The loop
1. **Name the behaviour.** For a use case, add or adjust the `R<n>:` line in its docstring first (A4).
2. **RED:** write one test that pins the behaviour, then run it:
   `make test PKG=<test file> ARGS='-k <name>'`. It must fail **for the expected reason**, such as
   an `AssertionError` on the value or an `ImportError` for a new module. If it fails for any other
   reason (a typo, a fixture error), fix the test and run it again. Paste the failing output.
3. **GREEN:** write the minimum code that passes, then re-run and paste the passing output.
4. **REFACTOR:** clean up with the tests green. `make check-fast` before moving on.
5. Repeat for the next rule. Commit per coherent step.

## Where the test goes
| Code under test | Test file | Doubles |
|---|---|---|
| `domain/…` | `tests/unit/domain/test_<module>.py` | none |
| `application/policies/<p>.py` | `tests/unit/policies/test_<p>.py` (+ Hypothesis, T6) | none |
| `application/use_cases/<uc>.py` | `tests/unit/use_cases/test_<uc>.py`, one `test_R<n>_*` per rule (T2) | fakes from `tests/<service>_fakes.py` (T3) |
| a new port | `tests/contract/test_<port>.py` run against fake + real (T4) | — |
| `infrastructure/…`, `interface/…` | `tests/integration/<area>/…` (T5) | real infra |

## Bugs
Reproduce the bug first. The regression test fails on the current code (T7). Then fix it.

## Signs you are not doing TDD
- You wrote the implementation and then "added tests".
- A new test passed on its first run: it may not test anything. Make it fail once on purpose.
- The test asserts that a mock was called instead of checking state or output (T3).
- You reached for `sleep`, real time or real network (T8, T10).
