---
name: performance-review
description: Performance and scale review — slow endpoints, heavy queries, N+1s, migrations that lock or rewrite tables, consumers falling behind, workflows timing out, or changes to query/loop/batch code. Measure first locally; in CI (the advisory `performance` focus) review the diff against the P1–P12 checklist.
---
# Performance review

Two modes. **Locally**, measure before you change anything: record a baseline number and the
command that produced it, and re-measure after the fix. **In CI** (the `performance` focus of
`code-review`), nothing can be measured: review the diff against the checklist below, and report
only what the diff shows. CI findings are always `advisory`; this focus never blocks a merge.

Each finding cites `path:line`, quotes the diff line, names the check (`P1`…`P12`), says what it
costs at scale (rows, requests, lock time) and gives a concrete fix.

## Checklist

**P1 — N+1 queries.** A query per item inside a loop over results:
- `for x in rows: await repo.get(x.id)` (or any port call that hits the database per item) in a
  use case, consumer or activity. Fix: one batched port method (`get_many(ids)`, `WHERE id = ANY`).
- A lazy-loaded relationship read inside a loop. Fix: `selectinload`/`joinedload` in the
  repository query.
- The same over HTTP: one outbound call per item where the API offers a batch endpoint.

**P2 — Unbounded reads (C10).** A list query with no `limit`/pagination and no comment saying why
it can't grow; `.all()` or `scalars().all()` on a growing table; `OFFSET` pagination on a large
table (prefer keyset: `WHERE (created_at, id) > (:c, :i)`); loading a whole table to filter or count
in Python.

**P3 — Missing or wrong indexes.** A new filter, join, `ORDER BY` or foreign-key column with no
index in the same change. With RLS every query also filters on `tenant_id`, so composite indexes
on tenant-scoped tables lead with `tenant_id`. A new unique rule should be a unique index.

**P4 — Migrations that lock or rewrite tables.** Migrations run as one transaction, so locks are
held until the whole revision commits, and a lock queued behind a long query blocks every later
query on that table. On a table that already holds data, flag:
- `op.create_index` without `postgresql_concurrently=True` (blocks writes for the whole build).
  Concurrent builds can't run in a transaction: use `with op.get_context().autocommit_block():`.
- `ADD COLUMN` with a volatile default (`now()`, `gen_random_uuid()`, `clock_timestamp()`): it
  rewrites the table. A constant default is fine.
- `ALTER COLUMN … TYPE` that rewrites the table (`int` → `bigint`, shrinking `varchar`, changing
  `numeric` precision).
- `SET NOT NULL` on a large table (full scan under an exclusive lock). Fix: add
  `CHECK (col IS NOT NULL) NOT VALID`, `VALIDATE CONSTRAINT` in a later revision, then
  `SET NOT NULL`.
- A new foreign key or `CHECK` without `NOT VALID` (scans the table under lock). Add it
  `NOT VALID`, then validate separately.
- A new unique constraint built in place. Fix: `CREATE UNIQUE INDEX CONCURRENTLY`, then
  `ADD CONSTRAINT … UNIQUE USING INDEX`.
- A data backfill (`UPDATE`/`INSERT … SELECT` over a whole table) inside a schema revision. Fix:
  a separate batched backfill, outside the schema migration.
- No `SET lock_timeout` before DDL on a busy table, so the migration waits instead of failing fast.
- Several heavy DDL steps on big tables in one revision. Split them.
Destructive changes (drop, rename) are a separate rule: expand-then-contract, and a human decides
(AGENTS.md).

**P5 — Work inside a transaction.** External I/O (HTTP, Kafka, Temporal calls) while a unit of
work is open; long computation while holding row locks; `SELECT … FOR UPDATE` over many rows or
in inconsistent order (deadlocks).

**P6 — Blocking the event loop.** Sync I/O in `async def` (`requests`, `time.sleep`, sync DB
drivers, file reads of unbounded size), CPU-heavy loops on the request path, and
`asyncio.gather` over an unbounded list with no concurrency limit.

**P7 — External I/O at scale (C6, `external-io`).** Retries without backoff and jitter (retry
storms), no total time budget, a missing batch where the API has one, or no client reuse
(a new client or connection per call).

**P8 — Kafka.** Heavy work or extra round trips per message, payloads that grow with data, a key
that creates a hot partition (a tenant id as key for a high-volume event), and handlers whose
work per message is unbounded.

**P9 — Temporal.** Large payloads in workflow inputs, results or signals (pass ids and let the activity load the data);
loops that grow history without `continue_as_new`; long activities without heartbeats; missing
`start_to_close_timeout`; fan-out without a limit.

**P10 — Memory.** Materialising a whole result set where streaming or batching works
(`yield_per`, chunked reads); unbounded caches (`lru_cache(maxsize=None)`, module dicts that grow
per tenant or per key).

**P11 — Hot-path complexity.** Quadratic loops over request- or tenant-sized collections, repeated
parsing or regex compilation inside loops, repeated serialisation of the same object.

**P12 — Request and response size.** Endpoints that return unbounded lists, request models that
accept unbounded lists with no `max_length`, and log lines emitted per row in hot loops.

## Budgets (local measurement)
API p95 < 200 ms, fewer than 10 queries per request, event-loop lag < 50 ms. Justify any breach.
To count queries, use an integration test with SQLAlchemy echo or an event listener on the
engine. For a query plan, use `EXPLAIN (ANALYZE, BUFFERS)` on realistic data volumes.
