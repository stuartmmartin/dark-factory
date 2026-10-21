---
paths:
  - "services/*/src/*/interface/workflows/**"
  - "libs/py/sb_workflows/**"
---
# Temporal workflows
- Workflow code is deterministic: no I/O, clock, randomness or unordered iteration (A12).
- Activities call exactly one use case; they are idempotent because they retry (A12).
- Deterministic workflow IDs `<name>-<tenant>-<key>`. Test with time-skipping + replay (T8).
