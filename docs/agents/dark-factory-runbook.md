# Dark-factory runbook

How to run long autonomous agent work (multi-task plans, overnight runs) without losing control.

## Before starting
1. **Spec, then plan.** Use the `spec` skill, then an implementation plan with bite-sized TDD
   tasks in `.work/<slug>/plan.md`. Working docs are gitignored and never committed.
2. **Isolate.** One git worktree per plan. Testcontainers give every test run its own
   databases, and each worktree's `make up` stack gets its own compose project and host ports
   (`make ports`), so parallel plans never wait on each other. Hooks fall back to the main
   checkout's `.venv`, so `make bootstrap` is needed once, in the main checkout.
3. **Baseline.** Run `make check` on the base commit and record any pre-existing failures in the
   ledger. From then on, agents may not "fix" or blame those without saying so.

## While running
- **Re-verify before you trust.** A claim from a previous session, plan or report is re-checked
  against the code before anything is built on it. If it doesn't reproduce, say so and stop.
- **One review, at the end.** A fresh implementer per task, each task green on its own tests and
  committed; one whole-branch review on the most capable model before the branch goes into
  `main`. Add a per-task review only for money, tenancy/RLS, auth or audit changes.
- **Ledger:** `.work/<slug>/ledger.md`, one line per event:
  - `Task N: complete (commits a..b, review clean)`
  - `Task N: fix round R/5 (…)`
  - `Task N: minor (deferred): …`
  - `Ruling: <decision> — <why> — <cost if wrong>`
  After a context reset, trust the ledger and `git log` over memory.
- **Rulings, not stalls.** Ambiguities get decided and ledgered. Only the items below stop the run.

## Stop and ask a human
- A change to the meaning of an `R<n>` business rule, money rounding, tenancy/RLS, auth or audit.
- A destructive or irreversible operation: a data migration that drops or rewrites data, a force
  push, or deleting anything that isn't scratch.
- Changing a guardrail file (A15).
- A plan so wrong that every way forward is a guess.

## Definition of done
Per task: a failing test that reproduced the missing behaviour, a passing test, the
implementation, the touched members' tests green, and one atomic commit (or a small series).
Per branch, before it goes into `main`: `make check` green, `tighten`, `harvest` over
`.work/<slug>/`, then the whole-branch `code-review` PASS. The worktree,
and its `.work/`, is deleted after merge, so anything not harvested is lost.

## Report format (end of run)
```
DONE:            tasks and commit ranges
SKIPPED/BLOCKED: what, and the exact blocker
RULINGS:         every Ruling: line, with its cost if wrong
DEFERRED:        minor findings for human triage
UNBLOCKED NEXT:  what can start now
```

## Open follow-ups

- `sb_kernel` mutation testing: 32 mutants survive; killing tests are not written yet.
