---
paths:
  - "**/tests/**"
---
# Tests
- Test first, RED for the right reason, then GREEN (T1). Rule tests are named `test_R<n>_*` (T2).
- Unit tests: fakes from `tests/<service>_fakes.py`, no mocks (T3). Integration: real infra, testcontainers (T5).
- No sleep; use FakeClock (T8). Synthetic data only (T10). Prefer make to run tests (T11). No silent skips (T13).
