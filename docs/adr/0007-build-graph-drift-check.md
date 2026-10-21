# ADR-0007: Build-graph artifacts generated from code and drift-checked in CI

- **Status:** Accepted
- **Date:** 2026-09-28

## Context
The build graph is only useful to agents (module index) and to CI (the affected-test matrix,
blast-radius queries) if it can be trusted to match the actual code at all times (spec §1, point
2 and point 3: "enforced by machines"). A hand-maintained graph — a YAML file someone edits when
they add a dependency — drifts the moment it's forgotten, and a drifted graph is worse than none,
because agents and CI would trust wrong information silently. The spec commits to generating these
artifacts from code and checking them for drift on every PR (spec §2 row 0007, §4.4).

## Decision
`tools/graph` (`sb-graph`) derives `docs/generated/build-graph.json`, `build-graph.md` (a Mermaid
diagram) and `module-index.md` from workspace member `pyproject.toml`s, `tach.toml`, and an AST
scan of actual imports — never from hand-maintained metadata. `make graph` regenerates and commits
these files; `make graph-check` regenerates in memory and fails, with a diff, if the committed
output is stale, if declared (pyproject) and actual (import) dependencies disagree, or if there is
a dependency cycle. `graph-check` runs in pre-commit (fast path, scoped to changed `pyproject.toml`
or `.py` files) and again in CI's `preflight` job on every PR, so a stale or hand-edited
`docs/generated/` fails the build rather than being silently trusted.

## Consequences
Agents and CI can treat `docs/generated/module-index.md` and the affected-test matrix as ground
truth without re-deriving it themselves, and `docs/generated/` never needs a human to keep it
current. The cost is a regeneration-and-commit step in the normal workflow (`make graph` after any
dependency or import change) and a small CI job on every PR; `.claude/settings.json` also denies
agents read access to the raw `build-graph.json` (spec §7.2) so they use the human-readable
module index instead of parsing generated JSON.

## Revisit when
`sb-graph generate` becomes slow enough (large repo, many members) to make `make graph-check`
a meaningful tax on every PR — at which point incremental/cached generation, not dropping the
drift check, is the fix.
