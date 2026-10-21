# ADR-0011: Temporal dev server; workflows in interface, activities call use cases

- **Status:** Accepted
- **Date:** 2026-09-28

## Context
Some processes (e.g. end-of-day balance snapshots, spec §6.4's
`EndOfDayBalanceSnapshotWorkflow`) are long-running, need retries and need to survive a process
restart, which is what Temporal is for. Two design questions follow: how to run Temporal locally
and in CI without a full server cluster, and where workflow/activity code should live so it stays
testable and doesn't become a second place business logic can hide (spec §2 row 0011, §7.6's
"stop-and-ask" list already calls out schema and auth changes as needing a human — workflow
determinism deserves the same care).

## Decision
Dev and CI run Temporal via `temporal server start-dev --ip 0.0.0.0 --db-filename
/data/temporal.db` inside `docker compose` (UI on :8233), not a production Temporal cluster (spec
§5.1). Workflow definitions live under `interface/workflows/`, use deterministic workflow IDs
(e.g. `eod-snapshot-{tenant}-{date}`, so a retry or duplicate schedule is naturally idempotent at
the workflow level), and contain no business logic themselves — a workflow's activities call into
`application/use_cases/` for every decision (`SnapshotBalances`, spec §6.2/§6.4). Determinism rules
for workflow code are documented in `.claude/rules/temporal.md`, loaded whenever
`**/interface/workflows/**` is touched (spec §7.1).

## Consequences
`start-dev` is a single binary with no external dependencies to stand up, keeping `make up infra`
fast and worktree-friendly, and workflows stay thin enough that the same `R<n>`-rule review applies
to the use cases they call rather than needing a separate workflow-logic review process. The cost
is that `start-dev`'s time-skipping test server is x64-only, so Apple Silicon runs it under
Rosetta locally and CI must use `ubuntu-latest` x64 runners (documented in
`docs/architecture/workflows.md`), and workflow determinism is a real constraint agents must be
taught, not something Python naturally enforces.

## Revisit when
A workload needs Temporal Cloud or a real multi-node cluster (`start-dev` no longer represents
production closely enough), or workflows accumulate enough branching that "activities call use
cases, workflows stay thin" is being violated in practice and needs a dedicated review check.
