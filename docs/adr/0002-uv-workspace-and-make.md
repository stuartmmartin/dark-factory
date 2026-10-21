# ADR-0002: uv workspace + Make as the build system

- **Status:** Accepted
- **Date:** 2026-09-28

## Context
We need one repo for many Python services and libraries, with TypeScript and Go likely later,
run by a 3–5 person team whose code is mostly written by AI agents. The options were Pants, Bazel,
Nx, moon, and uv workspaces plus Make. Pants and Bazel give fine-grained caching but add BUILD
files and sandboxes that agents handle poorly. Nx and moon add a Node or Rust toolchain for
marginal gain while the repo is Python-only.

## Decision
One uv workspace (`uv.lock`) for all Python members. Make is the single entrypoint for humans,
agents and CI. Affected-only testing comes from our own `sb-graph` (ADR-0007), not from a build
system.

## Consequences
Standard tools (`pytest`, `ruff`, `pyright`) behave exactly as documented, and agents already
know them. There is one version of each dependency across the repo, so a member that needs a
conflicting version must be split out. There is no remote build cache.

## Revisit when
CI wall time for an affected-only PR regularly exceeds 15 minutes, or a member needs a
conflicting dependency version.
