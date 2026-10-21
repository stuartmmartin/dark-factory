# ADR-0001: Monorepo lives in this repo as dark_factory

- **Status:** Accepted
- **Date:** 2026-09-28

## Context
The family office needs one place for the Python/FastAPI services, shared platform libraries,
and (later) TypeScript and Go code that will host many products over a ten-year horizon, built
mostly by AI agents and reviewed by humans (spec §1). We were starting from an existing checkout
(`sandbox`) rather than an empty directory, so the first decision was whether to build the
monorepo here or spin up a new, empty repository under a fresh name. A new repo would give a
clean history and a name that matches the project from day one; building in place keeps existing
history, remotes, CI credentials and any prior scaffolding usable immediately and avoids a
migration step before any other Plan-1 work can start.

## Decision
The monorepo is built directly in this repository (`sandbox`, with the internal project name
**dark_factory**). We do not create or migrate to a new repository. Everything the design calls
for — `AGENTS.md`/`CLAUDE.md`, `Makefile`/`mk/`, the uv workspace, `libs/py/`, `services/`,
`contracts/`, `deploy/k8s/`, `tools/`, `docs/`, `.claude/`, `.github/` (spec §3) — is added on top
of the current checkout. Pre-existing stray files unrelated to the design (e.g. `bak/`) are
cleaned up as part of the same work rather than carried forward.

## Consequences
No migration risk: there is no window where two repos both claim to be canonical, and existing
git history, issues and any external references to this repo keep working unchanged. The cost is
that the repo's external name (`sandbox`) and its internal project name (`dark_factory`) diverge,
so docs, READMEs and package names must consistently use `dark_factory`/`sb_*` rather than
`sandbox`, and anyone unfamiliar with the project needs a one-line explanation of that naming
mismatch (this ADR is that explanation).

## Revisit when
The family office spins out a product or entity that needs strict legal, licensing or access
separation from the rest of the codebase, or the repo name `sandbox` becomes actively confusing
to new engineers or agents (at which point renaming the repository, not re-migrating it, is the
smaller change).
