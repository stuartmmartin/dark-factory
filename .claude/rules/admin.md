---
paths:
  - "services/*/src/*/interface/admin/**"
  - "libs/py/sb_admin/**"
---
# SQLAdmin
- Acceptors wrap a pure policy: render its input model as a form, call it, and show inputs,
  outputs and the policy version. No DB writes (A5, A8).
- Model views for ledger-like tables are read-only; corrections happen through use cases (A3, A14).
