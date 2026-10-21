# ADR-0017: An advisory performance reviewer in CI

- **Status:** Proposed
- **Date:** 2026-10-01

## Context
The CI review gate (ADR-0016) runs security, architecture and engineering reviewers. Performance
and scale were covered only by the engineering focus's checks for unbounded queries (C10) and
missing timeouts (C6). N+1 queries, missing indexes, migrations that lock or rewrite tables,
I/O inside transactions, and Kafka and Temporal scale problems went unreviewed unless someone ran
the `performance-review` skill by hand. A performance finding from a static read of a diff is a
judgement about future load, with a higher false-positive rate than a rule violation, so making it
block the merge would train people to override the gate.

## Decision
`claude-review.yml` gets a fourth focus, `performance`, which runs the `code-review` skill with the
`performance-review` checklist (P1–P12). Triage requests it for service runtime code
(`services/*/src/**`), migrations (`services/*/migrations/**`) and the `sb_db`, `sb_messaging`,
`sb_workflows` and `sb_http` libraries. It is advisory: the triage matrix marks it
`blocking: false`, its job runs with `continue-on-error`, it skips the override check, and every
finding it reports is `advisory`. Its findings are posted on the PR like any other focus. The
other three focuses keep blocking exactly as before.

## Consequences
Authors and human reviewers see N+1s and risky migrations before merge, at the cost of one more
reviewer run on runtime changes. A PR that ignores a performance finding can still merge; a human
decides. The false-positive rate of this focus is tracked with the others (ADR-0016).

## Revisit when
After a quarter of findings: if most performance findings are acted on and false positives are
rare, make the migration-locking checks (P4) blocking, since a locked production table is costly and
the pattern is mechanical to detect. If findings are mostly ignored, tighten the checklist.
