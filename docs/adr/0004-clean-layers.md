# ADR-0004: CLEAN layers and composition root

- **Status:** Accepted
- **Date:** 2026-09-28

## Context
Business logic reviewable in isolation is a top-level success criterion for the foundation (spec
§1, point 4): "All business rules live in `application/use_cases/` and `application/policies/`."
For that to hold mechanically rather than by convention, every service needs the same, named
layers so an agent or reviewer can find logic without a tour of the codebase, and so import-linter
can express the dependency rule as a `layers` contract instead of a hand-reviewed rule. The
reference service `ledger` (spec §6) is structured exactly this way: `domain/` (entities, value
objects, invariants, domain events), `application/` (`ports.py`, `dto`, `policies/`, `use_cases/`),
`infrastructure/` (SQLAlchemy models, settings, adapters), `interface/` (HTTP routers, admin
views, consumers, Temporal workflows).

## Decision
Every service uses four layers — `domain`, `application` (`ports`, `dto`, `policies`,
`use_cases`), `infrastructure`, `interface` — plus a `bootstrap.py` composition root that wires
concrete infrastructure into the application's ports and is the only place allowed to import
across all four layers to do so. import-linter's `layers` contract enforces the dependency
direction per service: `interface > infrastructure > application > domain`, with `bootstrap`,
`main`, `worker` and `consumer` above all of them (spec §4.3). `domain` and `application` may
never import framework or infrastructure packages (`sqlalchemy`, `fastapi`, `sb_db`, …) — that
contract is a `forbidden` import-linter contract, not a convention.

## Consequences
A reviewer or agent can always find business logic in the same two directories regardless of
which service they're reading, and `pyright strict` on `domain`/`application` (spec §4.5) catches
type errors in exactly the code that matters most. The cost is boilerplate: every service, even a
small one, carries the full four-layer skeleton and a composition root, and a genuinely simple
CRUD service still pays the layering tax. `tools/templates/service` (Copier) exists so that cost
is paid once, by the template, not by every agent that scaffolds a service.

## Revisit when
A service is small enough, and stable enough, that the four-layer skeleton is pure ceremony with
no logic worth isolating — at which point we'd need a documented, reviewed exception rather than
silently drifting away from the layering per service.
