# ADR-0006: LSP + build graph + module index instead of RAG/graph DBs

- **Status:** Accepted
- **Date:** 2026-09-28

## Context
Agents need to answer "where is X defined", "what calls this", and "what would this change
affect" cheaply and correctly, without a tour of the codebase (spec §1, point 2). The available
approaches were: embeddings/RAG over the source, an AST-chunk index, a graph database fed by a
code-intelligence pipeline (e.g. Serena, GitNexus-style tools), or deterministic, in-repo tooling
built on top of the pyright LSP and a generated build graph. RAG and AST-chunk indexes go stale
the moment code changes and can silently answer with outdated context; a graph DB is a new,
stateful service to run, back up and keep in sync, and is a new data-exposure surface for a repo
where agents already have broad read access. At the monorepo's current and near-term scale
(nowhere near ~500k LOC, and Python-only), the cost of that infrastructure isn't justified by what
it buys over exact tools.

## Decision
Code intelligence is deterministic and derived fresh from code, not learned or cached
out-of-band: the pyright LSP plugin for symbol-level navigation and type information, plus
in-repo `sb-graph` build-graph tooling for member-level dependency questions
(`affected`/`blast-radius`/`deps`), plus a generated `docs/generated/module-index.md` (each
module's public API and one-line docstring summary) that agents read instead of opening files for
a first pass. No embeddings, no RAG, no AST-chunk index, and no graph-database MCP server are
introduced for this purpose.

## Consequences
Answers are never stale relative to the checked-out code (module index and build graph are
regenerated and drift-checked, ADR-0007), there's no new always-on data-exposure surface, and the
token cost of "explore the codebase" stays low and predictable. The trade-off is fuzzier
questions — "find code that looks like this" or "what's semantically similar to X" — aren't
answered natively; an agent has to fall back to `grep`/`Glob`, or a future addition, for that
class of question rather than getting it from this stack.

## Revisit when
The Python codebase approaches roughly 500k lines of code, or the first Go service arrives (a
second language the current LSP-plus-build-graph approach would need to generalize across) — at
that point, re-evaluate Serena- or GitNexus-style tooling against the then-current cost of staying
purely deterministic.
