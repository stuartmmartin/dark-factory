# ADR-0014: TS and Go workspaces added when first needed; contracts are language-neutral

- **Status:** Accepted
- **Date:** 2026-09-28

## Context
The monorepo is expected to host TypeScript frontends and Go services eventually, but today it is
Python-only (spec §11, out of scope: "TS frontend workspace and Go services. The seams are
documented, but no code is written."). Standing up a pnpm workspace or a `go.work` module graph,
plus the `sb_graph` collectors and `mk/ts.mk`/`mk/go.mk` targets to support them, before any actual
TypeScript or Go code exists would be scaffolding with nothing to validate it and a second (or
third) language's tooling to keep patched and working for zero current benefit.

## Decision
`apps/` (a pnpm workspace, for TypeScript) and a root `go.work` (for Go services under
`services/`) are added **only when the first actual TypeScript or Go code arrives**, not
speculatively. What *is* built now, because other languages will need it later: `sb_graph`'s
collector interface is pluggable and already has fixtures exercising `package.json`/`go.mod`
parsing even though the collectors aren't wired to real workspace members yet (spec §4.4), and
`contracts/` (event schemas, OpenAPI snapshots) is language-neutral from day one so a future
TypeScript or Go service can consume the same contracts a Python service does (spec §3, §14).

## Consequences
No team ever has to maintain pnpm or Go tooling that isn't backing real code, and YAGNI is
respected without leaving a design gap — the seam (`sb_graph` collectors, `mk/<lang>.mk`,
language-neutral `contracts/`) is deliberately kept ready. The cost is that adding the first
TypeScript or Go project is a small, one-time integration task (wiring the collector, adding the
`mk/*.mk` file, registering the workspace) rather than "it already works", and that seam has to be
kept accurate as `sb_graph` evolves even though nothing exercises it in anger yet.

## Revisit when
The first TypeScript app or Go service is actually being added — at which point this ADR's seam
gets exercised for real and `apps/`/`go.work` are created alongside it.
