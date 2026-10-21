---
paths:
  - "services/*/migrations/**"
---
# Alembic migrations
- Never edit a merged revision (the hook blocks it). Create a new one with `make db-revision`.
- Expand-then-contract only; destructive changes need a human (see AGENTS.md "stop and ask").
- New tenant-scoped tables get `tenant_id` + an RLS policy in the same revision (A13).
- Every revision round-trips: upgrade → downgrade → upgrade (`make db-check`).
