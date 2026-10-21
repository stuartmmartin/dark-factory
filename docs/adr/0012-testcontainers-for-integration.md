# ADR-0012: Integration tests use testcontainers

- **Status:** Accepted
- **Date:** 2026-09-28

## Context
Integration tests (`integration/db`, `integration/http`, `integration/messaging`,
`integration/workflows`, spec §6.5) need a real Postgres, and sometimes Kafka, to catch what fakes
can't — RLS isolation, append-only triggers, deferred constraints, outbox→Kafka→consumer
delivery. The `docker compose` stack (spec §5.1) is one shared, long-lived set of appliances meant
for interactive dev; pointing integration tests at it would make test runs depend on whatever state
is currently in that stack, break parallel agent worktrees (each with its own
`COMPOSE_PROJECT_NAME`) trying to run tests against the same containers, and require remembering
to run `make up infra` before `make test`.

## Decision
Integration tests spin up their own Postgres/Kafka containers per test session via
**testcontainers**, independent of whatever `docker compose` stack is or isn't running.
`docker compose` (`make up infra`/`make up <svc>`) is for the interactive dev runtime only. `make
test`/`make test-integration` need Docker running, but explicitly do **not** need `make up infra`
first (spec §8.1 step 8).

## Consequences
Test runs are hermetic and reproducible — no shared, mutable state between test runs or between
parallel agent worktrees — and an agent never needs to remember an extra setup step before running
integration tests. The cost is one more container-per-test-session startup, which is slower than
reusing a warm compose stack, and any state or extensions the compose Postgres has (e.g. specific
init scripts) has to be replicated in the testcontainers fixture (`sb_testing`) rather than assumed
shared.

## Revisit when
Per-session container startup measurably slows the test suite enough to justify a shared,
still-isolated container pool (e.g. one container reused across a test session with per-test
schema reset) instead of one container per session.
