---
paths:
  - "services/*/src/*/interface/http/**"
  - "libs/py/sb_http/**"
---
# HTTP interface
- Routers validate, call one use case, and map the result: no queries, no rules (A8).
- Tenant from `RequestContext` only, never from the body or query (A13). `Idempotency-Key` on writes.
- `response_model` on every route; decimals are strings on the wire (C3, C7).
- Tests assert the status before the body; schema tests for transport models (T9).
