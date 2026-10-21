---
paths:
  - "services/*/src/*/application/**"
---
# Application layer (use cases, policies, ports)
- Business logic lives here and only here (A3). Use case shape: one file, `<Verb><Noun>`, ports
  in `__init__`, `async def __call__(command) -> result`, rules `R1:`… in the docstring (A4).
- Every `R<n>` gets `test_R<n>_*` in `tests/unit/use_cases/test_<file>.py`, using fakes (T2, T3).
- Policies are pure: no I/O, no clock, deterministic, with pydantic inputs/outputs (A5).
- Import only stdlib, pydantic, sb_kernel and inner layers (A2). Money is `Money` (C3).
- A state change writes an audit event (A14) and emits events via the outbox (A11).
