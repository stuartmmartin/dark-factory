---
name: spec
description: Lightweight spec before non-trivial work — new use case, new endpoint/event/workflow, schema change, anything touching money, tenancy or audit. Rules become acceptance tests (R<n> → test_R<n>_*), plus operational criteria. Saves to .work/<slug>/spec.md (a working doc, harvested before review).
---
# Writing a spec

Keep it to one page. Save it as `.work/<slug>/spec.md` (gitignored: a working doc, never committed).
Put its Problem and rules in the PR body, and run the `harvest` skill before `/review`.

```markdown
# <Title>
## Problem
<Who needs what, and why now. One paragraph.>
## Business rules (acceptance criteria)
- R1: <rule, stated so a test can pin it> → test_R1_<behaviour>
- R2: …
## Interfaces
<Use case command/result, endpoint, event schema (contracts/events), workflow — whichever apply.>
## Operational criteria (at least two)
- Observability: <log events / metrics that prove it works in production>
- Kill switch: <flag or config that disables it without a deploy>
- Data volume: <largest realistic input; query bounds (C10)>
- Rollout / backfill: <expand-contract steps, backfill plan, reversibility>
## Files touched
<paths, grouped by layer>
## Out of scope
<what this deliberately does not do>
```

## Checks before you start implementing
- Every rule can be tested without the network or the clock (T8, T10).
- Nothing here needs a human decision from the AGENTS.md "stop and ask" list. If something does, ask first.
- Every file you'll change maps to a section of the spec. A change outside the spec is scope creep.
