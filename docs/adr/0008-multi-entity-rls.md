# ADR-0008: Multi-entity tenancy enforced with Postgres RLS

- **Status:** Accepted
- **Date:** 2026-09-28

## Context
dark_factory's tenants are legal entities of a family office — people, trusts, LLCs, partnerships
(spec §6.1's `LegalEntity`) — and a bug that leaks one entity's financial data into another's view
is a compliance failure, not a cosmetic one; "families and legal entities must be hard-isolated"
(spec §2 row 0008). Enforcing isolation only in application code (a `WHERE tenant_id = ?` an
engineer or agent must remember on every query) means a single missed clause, in any of many
repositories, is a data leak. Postgres Row-Level Security enforces the filter in the database
itself, beneath every query path including ad-hoc SQL run by a human or an MCP tool.

## Decision
Tenancy isolation is enforced with Postgres RLS from day one, not layered in later. Every
tenant-scoped table gets a `tenant_id` column and an RLS policy
`tenant_id = current_setting('app.tenant_id')::uuid`. The `app` database role that services use
has RLS enabled with **no** `BYPASSRLS`; only a separate `migrator` role (for schema changes) and
a `readonly` role (for MCP/agent read access) exist alongside it (spec §5.1). The unit of work
issues `SET LOCAL app.tenant_id` at the start of every transaction, sourced from the request or
activity context (spec §6.3, §10), so the policy has something to check against on every query.

## Consequences
A tenant-isolation bug becomes a database-level constraint violation or an empty result set
instead of a silent cross-tenant read, and it's provable: `integration/db` includes an explicit
RLS isolation test — tenant A cannot see tenant B's rows even via a raw `SELECT` as the `app` role
(spec §6.5). The cost is that every tenant-scoped query must run inside a transaction that has set
`app.tenant_id` correctly, which the UoW centralizes, and RLS policies must be kept in sync with
schema changes as part of every migration (the `alembic-migration` skill's checklist, spec §7.3).

## Revisit when
A workload needs to read or write across tenants in a single query for a legitimate reason (e.g.
cross-entity consolidated reporting) — that needs an explicit, audited bypass path (a distinct
role or a `SET LOCAL` escape hatch), not a weakening of the default policy.
