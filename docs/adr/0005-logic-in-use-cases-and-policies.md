# ADR-0005: Business logic lives in use cases and pure policies

- **Status:** Accepted
- **Date:** 2026-09-28

## Context
Reviewers need one place to look for behavior that a human must approve rather than trust to an
agent (spec §1, point 4). If logic can live in the domain, in application, *and* scattered through
infrastructure and interface adapters, no single directory is trustworthy on its own. The
reference service demonstrates the intended split precisely: the domain (`LegalEntity`,
`Account`, `JournalEntry`, `Posting`) holds only entities, value objects and invariants enforced
in constructors (e.g. postings balance to zero per currency); all decision logic sits in
`application/use_cases/*.py`, each with a module docstring listing numbered rules `R1…Rn`, and in
`application/policies/*.py`, which are pure functions (`allocate`, `balance`) with no I/O (spec
§6.1–§6.2). Policies being pure and side-effect-free is also what lets them be exposed directly to
humans through SQLAdmin acceptors (spec §6.4, §7.3 `admin-acceptor` skill) for manual
verification without touching the database.

## Decision
The domain holds only entities, value objects and invariants — no orchestration, no I/O, no
decision rules beyond "is this object internally valid". All decision logic is either a **use
case** (orchestrates ports, enforces numbered rules `R1…Rn`, one rule ↔ one `test_R<n>_*` test) or
a **pure policy** (a plain function over value types, no ports, no I/O, safe to run from an
acceptor UI or a Hypothesis property test). Nothing outside `application/use_cases/` and
`application/policies/` is allowed to contain a business rule; infrastructure and interface code
only translates and delegates.

## Consequences
Reviewers get a fixed, small surface to read for every change that touches business rules — two
directories, plus the `R<n>` ↔ `test_R<n>_*` binding that `sb-checks` enforces mechanically (spec
§4.3). Policies being pure means they compose, property-test well under Hypothesis, and can be
exercised by non-engineers through the admin acceptors. The cost is discipline: it is tempting
to let a repository or an HTTP handler make "just one small decision," and that temptation has to
be caught by the architecture-reviewer agent and the layer/forbidden import-linter contracts, not
assumed away.

## Revisit when
A rule genuinely cannot be expressed as either a use-case orchestration step or a pure policy
function (for example, a decision that must run outside a transaction boundary and cannot be
modeled as a port) — at which point the two-category split itself, not just an individual rule,
needs re-examining.
