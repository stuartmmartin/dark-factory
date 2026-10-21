# Testing conventions (T-rules)

## Test layout per service
```
tests/unit/domain/        entities & value objects
tests/unit/policies/      pure calculators (+ Hypothesis properties)
tests/unit/use_cases/     one file per use case; test_R<n>_* per rule; fakes only
tests/<service>_fakes.py  in-memory implementations of the application ports
tests/contract/           one suite run against fake AND real adapters
tests/integration/        real Postgres/Kafka/Temporal via testcontainers (auto-marked)
```

### T1 — Test first
Write the failing test first and run it. Confirm it fails **for the expected reason**, then
write the minimum code to pass it. Paste the RED and GREEN output as evidence (see the `tdd` skill).
*Enforced:* review (evidence in the PR / report).

### T2 — Every business rule has a named test
Each `R<n>` in a use case docstring has `test_R<n>_<behaviour>`.
*Enforced:* `use-case-rules` check.

### T3 — Fakes, not mocks, in unit tests
Unit tests use in-memory fakes of the ports from `tests/<service>_fakes.py` (a unique module
name: one pytest session shares `sys.modules` across services). A fake implements the
Protocol, so signature drift breaks it; a mock accepts anything, which makes the test tautological.
*Enforced:* `no-mock-in-unit` check.

### T4 — Contract tests keep fakes honest
Run each port's contract suite against both the fake and the real adapter.
*Enforced:* review (a new port needs a contract suite).

### T5 — Integration tests are real
Integration tests live under `tests/integration/` and run against real Postgres, Kafka and
Temporal via testcontainers. Never use SQLite as a stand-in for Postgres.
*Enforced:* auto `integration` marker; testcontainers fixtures in `sb_testing` (from Plan 3); review.

### T6 — Numbers get properties
Policies with numeric logic get Hypothesis property tests (sums preserved, bounds,
idempotence, determinism).
*Enforced:* review; nightly mutation testing (T12).

### T7 — Bugs start with a reproduction
A bug fix begins with a test that reproduces the bug. The test fails on the old code and passes
on the fix.
*Enforced:* review.

### T8 — No real waiting
Never call `sleep`. Time comes from `FakeClock`. Temporal tests use the time-skipping environment.
*Enforced:* review.

### T9 — Boundary tests
HTTP tests assert the status code before parsing the body. Every transport model has valid,
missing-field and invalid-value tests.
*Enforced:* review.

### T10 — Hermetic and synthetic
Tests make no real network calls: the forbid-network guard is autouse. Test data is synthetic
(Faker/Hypothesis), never real family or production data.
*Enforced:* `sb_testing` forbid-network guard (from Plan 3); review; security review.

### T11 — Make is the default test runner
Prefer `make test PKG=… ARGS=…`, `make test-unit` and `make test-affected`: they run what CI runs.
Raw `uv run pytest …` is fine for quick iteration. Each run gets its own testcontainers
Postgres/Kafka, so parallel runs in different worktrees never collide.
*Enforced:* convention (CI runs the make targets).

### T12 — Coverage and mutation
All code in service `domain/`, `application/` and `sb_kernel` needs 100% statement and branch
coverage. `make coverage` runs non-integration tests and measures unimported modules too,
including namespace packages. It writes `coverage.xml` and fails below 100%; do not lower the
threshold or exclude uncovered logic. mutmut runs nightly on the logic layers, and each
surviving mutant becomes the next task.
*Enforced:* `make coverage`, `make check`, required CI coverage job; nightly mutation workflow.

### T13 — No silent skips
Don't `skip` or `xfail` without a linked issue in the reason. xfail is strict.
*Enforced:* pytest `xfail_strict`; review.
