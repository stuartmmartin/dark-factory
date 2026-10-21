---
name: harvest
description: Distil a larger change's working docs (.work/<slug>/ — spec, plan, ledger, rulings, trade-offs, investigations, notes) into durable knowledge where future agents will look — a test or check, a code comment, the member's CLAUDE.md, CONTEXT.md, an ADR or a ticket. Use once per branch, when it is ready to go into main and before /review, if it had working docs; skip small fixes that had none.
---
# Harvesting knowledge

Working docs (tier 1) are never committed. They live in gitignored `.work/<slug>/` and serve one
change. What outlives the change (tier 2) goes where an agent working on that code already looks.
The code, tests and `docs/generated/` already say **what** and **where**; harvest only what they
can't say.

## When
- The branch had anything under `.work/<slug>/`. Run this after the last code change, before `/review`.
- Nothing there: skip, and put `Knowledge harvested: none (no working docs)` in the PR.

## Keep
- **Why**: a decision with a real alternative, and why the obvious one was rejected.
- **Traps**: looks wrong but is deliberate, looks safe but isn't, order or setup that matters.
- **Not built yet**: deferred scope, known gaps, follow-ups ("double-entry is deferred").
- **Human rulings**, especially ones flagged for sign-off.

## Drop
Task lists, progress and status, anything the code, tests or generated docs already show,
session or tooling notes, and anything superseded later in the same notes.

## Place each item in the first home that fits
| Item | Home |
|---|---|
| An invariant or trap a test or check can pin | a test (`test_R<n>_*`, via `tdd`) or a check |
| Local: "this looks wrong, because…" | a comment next to the code |
| Member-wide trap or operating note | that member's `CLAUDE.md` |
| A domain term | that service's `CONTEXT.md` |
| A decision with real alternatives, or scope deferred by design | a new ADR in `docs/adr/` (next number, one page) |
| Any other work not done (follow-ups, known gaps) | a tracker ticket, linked from the PR |

- One fact, one home. Link to it, don't copy it.
- Edit a home rather than append to it: remove or rewrite anything the change made stale.
- A member's `CLAUDE.md` stays under the size limit `agent-lint` enforces. If it's full, move
  items into tests or comments.
- Never harvest into `docs/superpowers/`, `docs/agents/ledgers/`, `docs/reviews/` or
  `docs/investigations/`, and never link to `.work/` (it doesn't exist in CI).
- Stop and ask before an ADR records a decision about `R<n>` meaning, money rounding,
  tenancy/RLS, auth or audit (see AGENTS.md).

## Steps
1. Read everything in `.work/<slug>/`. List each keep-worthy item as `H1…Hn`, with its source file.
2. Give each item a home and a one-line reason, or `drop` and the reason.
3. Write the homes. Tests go through `tdd`: red first.
4. Run `make agent-lint` (links, size limits, no working docs) and `make check-fast`.
5. Add this to the PR body, so the reviewer can check nothing was lost:
   ```
   ## Knowledge harvested
   | # | Item | Home (or "dropped: why") |
   ```
6. After the PR merges, delete `.work/<slug>/` (or remove the worktree).
