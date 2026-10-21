---
paths:
  - "services/*/src/*/infrastructure/**"
  - "libs/py/sb_db/**"
  - "libs/py/sb_messaging/**"
---
# Infrastructure layer
- Adapters implement `application/ports.py` Protocols and map ORM/SDK types to domain objects;
  those types never leave this layer (A6).
- Typed SQLAlchemy 2.0, bounded queries, no string SQL (C10). Explicit timeouts and bounded
  retries on all I/O (C6; see the `external-io` skill).
- Env vars only in `settings.py` (C5). Tenant-scoped tables have `tenant_id` + RLS (A13).
- Publish events by writing the outbox row in the caller's unit of work (A11).
