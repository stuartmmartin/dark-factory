---
name: alembic-migration
description: Create or change database schema for a service — new table, column, index, RLS policy, append-only trigger — with Alembic and sb_db. Expand-then-contract only; never edit merged revisions.
---
# Alembic migration
Reference: [data architecture](../../../docs/architecture/data.md). Rules: A13 (tenancy), A14
(audit), C10 (typed SQL).

1. Change the SQLAlchemy models first. Build the service's declarative base with
   `sb_db.base.make_base()` (naming convention included). Tenant-owned tables use the
   `sb_db.base.TenantScoped` mixin (`tenant_id uuid NOT NULL`, indexed) (A13).
2. The service's `alembic/env.py` is one line of glue: `run_migrations(url, target_metadata)` from
   `sb_db.alembic_env`. Migrations connect as `sb_migrator`, never as `sb_app`. Include
   `install_platform_tables(metadata)` so the outbox, inbox, audit and idempotency tables are part
   of the metadata. Create the service database on first migrate with `sb_db.database.ensure_database`.
3. **The initial revision of every service** creates the platform tables and then applies
   `apply(op, platform_table_ddl())` (from `sb_db.rls`). That is the required RLS state for
   `audit_events` and `idempotency_keys` and makes `audit_events` append-only. Do not skip it: the
   library's guarantees (tenant isolation, tamper-evident audit) depend on it.
4. Autogenerate the revision, then **read it**. Autogenerate misses RLS policies, triggers and some
   type changes.
5. For every new tenant-scoped table, add to the revision `upgrade()`:
   `from sb_db.rls import apply, enable_rls_sql` then `apply(op, enable_rls_sql("<table>"))`.
   This enables and FORCEs RLS and creates the `tenant_id` policy. For append-only tables add
   `apply(op, append_only_sql("<table>"))`. That blocks UPDATE, DELETE **and TRUNCATE**, even for
   the owner. Table names must be lowercase `[schema.]table` identifiers: the helpers raise
   `ValueError` on anything else.
6. Grants: `sb_readonly` has no grants by default. For each table it may read, add
   `op.execute("GRANT SELECT ON <table> TO sb_readonly")`. The runtime role `sb_app` also needs
   its table privileges granted by the migration.
7. Write a `downgrade()` that fully reverses the revision. A destructive step (dropping or renaming
   a column or table, narrowing a type) is **not allowed** in the same release as the code change.
   Do it expand-then-contract across two PRs, and stop and ask a human first (AGENTS.md).
8. Add or extend an integration test that proves the new constraint or RLS behaviour against real
   Postgres (T5). It must run as `sb_app` (NOBYPASSRLS): `sb_migrator` has BYPASSRLS and sees
   every tenant's rows, so a test as that role proves nothing about isolation.
9. Check the revision chain has a single head and that `upgrade -> downgrade -> upgrade` works.
   Service-level `make db-*` targets arrive with the service template. Until it lands, ask a
   human to run the round-trip check, rather than running raw `alembic` (the hook redirects it).

Never edit a revision that is already on `origin/main` (the hook blocks it). Write a new one.
